"""`subset-db` against the mini fixture (#225).

The fixture's two datasets differ in `deployTo` — mini_perturb is
[dev, prod], mini_embargoed is [dev] — and they deliberately overlap: some
genes appear in both (a prod subset must keep them but shrink num_datasets),
some only in the dev-only one (a prod subset must drop them entirely).

The claim under test is equivalence: subsetting the superset must produce the
same thing as building only the prod datasets from scratch. That is what makes
"build once on dev, subset at promotion" safe.
"""

from __future__ import annotations

import io
import sqlite3
import zipfile
from pathlib import Path

import pytest

from processing.config import get_sspsygene_config
from processing.destination_guard import (
    DestinationGuardError,
    verify_destination,
)
from processing.sq_load import load_db
from processing.subset_db import SubsetError, subset_db

MEMBER = "mini_perturb_deg"
EMBARGOED = "mini_embargoed_deg"


def _build_superset(config) -> Path:
    load_db(
        config.out_db,
        config.tables_config.tables,
        assay_types=config.global_config.get("assayTypes", {}),
        condition_types=config.global_config.get("conditionTypes", {}),
        organism_types=config.global_config.get("organismTypes", {}),
        modalities=config.global_config.get("modalities", []),
        skip_missing=False,
        no_index=True,
        data_dir=config.base_dir,
        skip_gene_descriptions=True,
    )
    return config.out_db


def _rows(db: Path, sql: str) -> set[tuple]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {tuple(r) for r in conn.execute(sql)}
    finally:
        conn.close()


def _scalar(db: Path, sql: str):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


# Built-superset bytes, cached for the module. `load_db` against the mini
# fixture costs ~13s — almost all of it parsing the real HGNC / MGI / Alliance
# homology files, which are identical on every call here. Rebuilding it per
# test made this module alone ~140s of a ~280s suite. The inputs are fixed, so
# one build and a file copy per test is equivalent and ~100x cheaper.
_SUPERSET_BYTES: bytes | None = None


@pytest.fixture
def superset(mini_fixture: Path) -> tuple[Path, Path]:
    """(built superset DB, dataset config root).

    `mini_fixture` stays function-scoped — it owns the SSPSYGENE_* env and the
    module-cache resets, which tests do depend on being fresh. Only the
    expensive build result is reused.
    """
    global _SUPERSET_BYTES
    config = get_sspsygene_config()
    if _SUPERSET_BYTES is None:
        _build_superset(config)
        _SUPERSET_BYTES = config.out_db.read_bytes()
    else:
        config.out_db.write_bytes(_SUPERSET_BYTES)
    return config.out_db, config.base_dir / "datasets"


def test_prod_subset_keeps_only_the_prod_dataset(
    superset: tuple[Path, Path], tmp_path: Path
) -> None:
    src, config_root = superset
    out = tmp_path / "prod.db"
    subset_db(src, out, "prod", config_root=config_root)

    assert _rows(src, "SELECT table_name FROM data_tables") == {
        (MEMBER,),
        (EMBARGOED,),
    }
    assert _rows(out, "SELECT table_name FROM data_tables") == {(MEMBER,)}

    # Fail-closed: the dev-only table is not merely hidden, it is absent.
    objects = _rows(out, "SELECT name FROM sqlite_master WHERE type='table'")
    names = {o[0] for o in objects}
    assert EMBARGOED not in names
    assert not any(n.startswith(f"{EMBARGOED}__") for n in names)
    assert f"{MEMBER}__gene" in names


def test_prod_subset_passes_its_own_destination_check(
    superset: tuple[Path, Path], tmp_path: Path
) -> None:
    src, config_root = superset
    out = tmp_path / "prod.db"
    subset_db(src, out, "prod", config_root=config_root)
    verify_destination(out, "prod", config_root=config_root)

    # ...and the superset it came from is, correctly, NOT valid for prod.
    with pytest.raises(DestinationGuardError):
        verify_destination(src, "prod", config_root=config_root)


def test_shared_genes_survive_with_a_shrunken_dataset_list(
    superset: tuple[Path, Path], tmp_path: Path
) -> None:
    """Tcf4 is in both fixtures. It must survive the prod subset, and its
    dataset_names / num_datasets must no longer mention the dev-only table."""
    src, config_root = superset
    out = tmp_path / "prod.db"
    subset_db(src, out, "prod", config_root=config_root)

    before = _rows(
        src,
        "SELECT dataset_names, num_datasets FROM central_gene WHERE id IN "
        "(SELECT central_gene_id FROM central_gene_usage "
        " WHERE matched_name = 'Tcf4')",
    )
    after = _rows(
        out,
        "SELECT dataset_names, num_datasets FROM central_gene WHERE id IN "
        "(SELECT central_gene_id FROM central_gene_usage "
        " WHERE matched_name = 'Tcf4')",
    )
    assert before and after, "Tcf4 must be present in both"
    assert any(EMBARGOED in (names or "") for names, _ in before)
    assert not any(EMBARGOED in (names or "") for names, _ in after)
    for names, n in after:
        assert n == len({x for x in (names or "").split(",") if x})


def test_genes_only_in_the_dev_only_dataset_are_dropped(
    superset: tuple[Path, Path], tmp_path: Path
) -> None:
    """Pax6 appears only in mini_embargoed; Gm88888 is its record_values stub.
    Neither may survive into prod — including the manually-added stub, which
    is why the stub path records usages at all."""
    src, config_root = superset
    out = tmp_path / "prod.db"
    subset_db(src, out, "prod", config_root=config_root)

    for name in ("Pax6", "Gm88888", "NonTarget2"):
        assert _scalar(
            src,
            "SELECT count(*) FROM central_gene_usage "
            f"WHERE matched_name = '{name}'",
        ), f"{name} should exist in the superset"
        assert not _scalar(
            out,
            "SELECT count(*) FROM central_gene_usage "
            f"WHERE matched_name = '{name}'",
        ), f"{name} must not survive into prod"

    # The prod-only stubs are untouched.
    assert _scalar(
        out,
        "SELECT count(*) FROM central_gene_usage "
        "WHERE matched_name IN ('Gm99999', 'NonTarget1')",
    )


def test_subset_matches_a_from_scratch_prod_only_build(
    superset: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The equivalence the whole build-once/subset-at-promote design rests on.

    Compared on natural keys and with the comma-joined columns normalized:
    `central_gene.id` is a positional surrogate (`row_id = len(entries)`), so
    manually-added stub entries are numbered differently when a dataset is
    absent from the build entirely, and `dataset_names` / `mouse_symbols` are
    `",".join(<set>)`, whose order differs between any two builds.
    """
    src, config_root = superset
    out = tmp_path / "prod.db"
    subset_db(src, out, "prod", config_root=config_root)

    # Build a prod-only DB from scratch, from a PRIVATE copy of the data root
    # with the dev-only dataset removed. Deleting from `config_root` directly
    # would mutate the session-scoped mini_data_root and leak into whichever
    # test runs next.
    import shutil

    from processing import central_gene_table as cgt
    from processing import config as config_module

    private_root = tmp_path / "prod-only-root"
    shutil.copytree(config_root.parent, private_root, symlinks=True)
    shutil.rmtree(private_root / "datasets" / "mini_embargoed")
    monkeypatch.setenv("SSPSYGENE_DATA_DIR", str(private_root))
    config_module.get_sspsygene_config.cache_clear()
    cgt._CENTRAL_GENE_TABLE = None
    scratch_config = get_sspsygene_config()
    scratch = tmp_path / "scratch.db"
    scratch_config.out_db = scratch
    _build_superset(scratch_config)

    assert _rows(out, "SELECT table_name FROM data_tables") == _rows(
        scratch, "SELECT table_name FROM data_tables"
    )

    def genes(db: Path) -> dict:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            out_map = {}
            for (
                sym,
                hgnc,
                entrez,
                mouse,
                hsyn,
                msyn,
                names,
                n,
                manual,
                kind,
            ) in conn.execute(
                "SELECT human_symbol, hgnc_id, human_entrez_gene, mouse_symbols,"
                " human_synonyms, mouse_synonyms, dataset_names, num_datasets,"
                " manually_added, kind FROM central_gene"
            ):
                split = lambda v: tuple(  # noqa: E731
                    sorted(x for x in (v or "").split(",") if x)
                )
                out_map[(sym, hgnc, entrez, kind, manual)] = (
                    split(mouse),
                    split(hsyn),
                    split(msyn),
                    split(names),
                    n,
                )
            return out_map
        finally:
            conn.close()

    assert genes(out) == genes(scratch)

    for sql in (
        "SELECT matched_name, table_name, species FROM central_gene_usage",
        "SELECT species, synonym FROM extra_gene_synonyms",
        "SELECT symbol FROM extra_mouse_symbols",
        "SELECT ensembl_id, symbol, species FROM ensembl_to_symbol",
        "SELECT table_name, date, message FROM changelog_entries",
        "SELECT path FROM export_files",
    ):
        assert _rows(out, sql) == _rows(scratch, sql), sql


def test_exports_are_regenerated_without_the_dev_only_dataset(
    superset: tuple[Path, Path], tmp_path: Path
) -> None:
    """write_exports scopes itself to the file's own data_tables, so the
    subset's download bundle needs no filtering logic — but the zip is what a
    user actually receives, so assert on it directly."""
    src, config_root = superset
    out = tmp_path / "prod.db"
    subset_db(src, out, "prod", config_root=config_root)

    paths = {p for (p,) in _rows(out, "SELECT path FROM export_files")}
    assert f"tables/{MEMBER}.tsv" in paths
    assert not any(EMBARGOED in p for p in paths)

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        blob = conn.execute(
            "SELECT content FROM export_files WHERE path = 'all-tables.zip'"
        ).fetchone()[0]
    finally:
        conn.close()
    members = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert any(MEMBER in m for m in members)
    assert not any(EMBARGOED in m for m in members)


def test_subset_keeps_the_superset_build_uuid(
    superset: tuple[Path, Path], tmp_path: Path
) -> None:
    """It is the same build, so the meta / overview DBs promoted beside it must
    still match (#225)."""
    src, config_root = superset
    out = tmp_path / "prod.db"
    subset_db(src, out, "prod", config_root=config_root)
    assert _scalar(
        out, "SELECT value FROM build_info WHERE key = 'build_uuid'"
    ) == _scalar(src, "SELECT value FROM build_info WHERE key = 'build_uuid'")


def test_refuses_an_unknown_table_it_cannot_classify(
    superset: tuple[Path, Path], tmp_path: Path
) -> None:
    """The fail-closed rule: a table added to the build after this module was
    written stops the promotion rather than being copied or dropped silently."""
    src, config_root = superset
    conn = sqlite3.connect(src)
    conn.execute("CREATE TABLE some_new_pipeline_table (x INTEGER)")
    conn.commit()
    conn.close()

    with pytest.raises(SubsetError, match="does not know how to classify"):
        subset_db(src, tmp_path / "prod.db", "prod", config_root=config_root)


def test_refuses_a_destination_with_no_members(
    superset: tuple[Path, Path], tmp_path: Path
) -> None:
    """int is in no fixture's deployTo, so an int subset would be empty."""
    src, config_root = superset
    with pytest.raises(SubsetError, match="no table"):
        subset_db(src, tmp_path / "int.db", "int", config_root=config_root)


def test_refuses_to_subset_onto_itself(
    superset: tuple[Path, Path],
) -> None:
    src, config_root = superset
    with pytest.raises(SubsetError, match="onto itself"):
        subset_db(src, src, "prod", config_root=config_root)


def test_leaves_no_staging_file_behind(
    superset: tuple[Path, Path], tmp_path: Path
) -> None:
    src, config_root = superset
    out = tmp_path / "prod.db"
    subset_db(src, out, "prod", config_root=config_root)
    assert out.exists()
    for suffix in (".new", ".new-wal", ".new-shm", "-wal", "-shm"):
        assert not out.with_name(out.name + suffix).exists(), suffix
