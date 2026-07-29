"""Tests for `promote-dev-to-prod` / `promote-dev-to-int` (#178, #225).

Since #225 a promotion is no longer a straight file copy: dev builds the
superset, `subset-db` derives the destination's DB on dev, and the destination
guard checks the result before the swap and again after it.

These tests drive the real LOCAL transport against temp dirs standing in for
the /hive trees (no SSH, no network), so they exercise the actual cp/mv swap
and the real guards. The one substitution is `_site_sspsygene_cmd`, which
normally builds a `conda run -n sspsygene …` invocation inside a site checkout;
here it runs the subcommand in-process against the temp tree instead.
"""

from __future__ import annotations

import shlex
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

from processing import deploy
from processing.deploy import (
    DeployError,
    _resolve_promote_local,
    run_promote_dev_to_int,
    run_promote_dev_to_prod,
)

PUBLIC = "public_degs"
EMBARGOED = "secret_degs"


def _make_dataset_db(path: Path, labels: dict[str, list[str]]) -> None:
    """A main DB shaped enough for subset-db and the guard to work on.

    `labels` maps dataset name -> deployTo. Each dataset owns one data table
    plus one link table, and one gene used by every table.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        -- Every column exports._list_data_tables selects, so the real
        -- write_exports runs against this fixture unmodified.
        CREATE TABLE data_tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT, dataset TEXT, short_label TEXT, medium_label TEXT,
            long_label TEXT, description TEXT, gene_columns TEXT,
            gene_species TEXT, display_columns TEXT, scalar_columns TEXT,
            link_tables TEXT, links TEXT, categories TEXT, source TEXT,
            assay TEXT, condition TEXT, field_labels TEXT, column_labels TEXT,
            organism TEXT, organism_key TEXT,
            publication_first_author TEXT, publication_last_author TEXT,
            publication_author_count INTEGER, publication_authors TEXT,
            publication_year INTEGER, publication_journal TEXT,
            publication_doi TEXT, publication_pmid TEXT,
            publication_sspsygene_grants TEXT,
            pvalue_column TEXT, fdr_column TEXT, effect_column TEXT,
            preprocessing TEXT);
        CREATE TABLE dataset_destinations (
            dataset TEXT NOT NULL, table_name TEXT NOT NULL,
            destination TEXT NOT NULL,
            PRIMARY KEY (dataset, table_name, destination)) WITHOUT ROWID;
        CREATE TABLE changelog_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT, date TEXT, message TEXT);
        CREATE TABLE central_gene (
            id INTEGER PRIMARY KEY, human_symbol TEXT, human_entrez_gene INTEGER,
            hgnc_id TEXT, mouse_symbols TEXT, mouse_mgi_accession_ids TEXT,
            mouse_ensembl_genes TEXT, human_synonyms TEXT, mouse_synonyms TEXT,
            dataset_names TEXT, num_datasets INTEGER, manually_added BOOLEAN,
            kind TEXT NOT NULL DEFAULT 'gene');
        CREATE TABLE central_gene_usage (
            central_gene_id INTEGER NOT NULL, table_name TEXT NOT NULL,
            species TEXT NOT NULL, matched_name TEXT NOT NULL,
            PRIMARY KEY (central_gene_id, table_name, species, matched_name))
            WITHOUT ROWID;
        CREATE TABLE extra_gene_synonyms (
            id INTEGER PRIMARY KEY AUTOINCREMENT, central_gene_id INTEGER,
            species TEXT, synonym TEXT);
        CREATE TABLE extra_mouse_symbols (
            id INTEGER PRIMARY KEY, symbol TEXT, central_gene_id INTEGER);
        CREATE TABLE ensembl_to_symbol (
            ensembl_id TEXT PRIMARY KEY, symbol TEXT NOT NULL,
            central_gene_id INTEGER NOT NULL, species TEXT NOT NULL);
        CREATE TABLE assay_types (key TEXT PRIMARY KEY, label TEXT);
        CREATE TABLE condition_types (key TEXT PRIMARY KEY, label TEXT);
        CREATE TABLE organism_types (key TEXT PRIMARY KEY, label TEXT);
        CREATE TABLE modalities (
            key TEXT PRIMARY KEY, label TEXT, assay_types TEXT,
            always_show INTEGER, sort_order INTEGER);
        CREATE TABLE build_info (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    conn.execute("INSERT INTO build_info VALUES ('build_uuid', 'promote-test')")
    conn.execute("INSERT INTO assay_types VALUES ('expression', 'Expression')")
    for dataset, destinations in labels.items():
        table = f"{dataset}_degs"
        link = f"{table}__gene"
        conn.execute(
            "INSERT INTO data_tables (table_name, dataset, link_tables, "
            "display_columns, gene_columns, gene_species) VALUES (?,?,?,?,?,?)",
            (table, dataset, f"gene:{link}:target", "gene,pvalue", "gene", "human"),
        )
        for destination in destinations:
            conn.execute(
                "INSERT INTO dataset_destinations VALUES (?,?,?)",
                (dataset, table, destination),
            )
        conn.execute(f'CREATE TABLE "{table}" (id INTEGER, gene TEXT, pvalue REAL)')
        conn.execute(f'INSERT INTO "{table}" VALUES (1, ' "'TCF4', 0.01)")
        conn.execute(
            f'CREATE TABLE "{link}" (central_gene_id INTEGER NOT NULL, '
            f"id INTEGER NOT NULL, PRIMARY KEY (central_gene_id, id)) "
            f"WITHOUT ROWID"
        )
        conn.execute(f'INSERT INTO "{link}" VALUES (1, 1)')
        conn.execute(
            "INSERT INTO changelog_entries (table_name, date, message) "
            "VALUES (?, '2026-01-01', 'note')",
            (table,),
        )
        conn.execute(
            "INSERT INTO central_gene_usage VALUES (1, ?, 'human', 'TCF4')",
            (table,),
        )
    tables = sorted(f"{d}_degs" for d in labels)
    conn.execute(
        "INSERT INTO central_gene (id, human_symbol, dataset_names, "
        "num_datasets, manually_added, kind) VALUES (1, 'TCF4', ?, ?, 0, 'gene')",
        (",".join(tables), len(tables)),
    )
    conn.commit()
    conn.close()


def _make_simple_db(path: Path, table: str, n_rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {table}(x)")
    conn.executemany(f"INSERT INTO {table} VALUES(?)", [(i,) for i in range(n_rows)])
    conn.commit()
    conn.close()


def _write_configs(datasets_dir: Path, labels: dict[str, list[str]]) -> None:
    for dataset, destinations in labels.items():
        d = datasets_dir / dataset
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "deployTo": destinations,
                    "tables": [
                        {"table": f"{dataset}_degs", "description": "d"}
                    ],
                }
            )
        )


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {r[0] for r in conn.execute("SELECT table_name FROM data_tables")}
    finally:
        conn.close()


def _count(path: Path, table: str) -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


LABELS = {"public": ["dev", "prod", "int"], "secret": ["dev"]}


@pytest.fixture
def hive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Temp /hive trees, plus a locally-runnable `sspsygene` invocation.

    `_site_sspsygene_cmd` normally builds a `conda run` command inside a site
    checkout. Here it runs the same subcommand through this interpreter against
    the temp tree, so the promote path's real subset-db and verify-destination
    steps actually execute.
    """
    dev = tmp_path / "sspsygene_website_dev"
    prod = tmp_path / "sspsygene_website"
    internal = tmp_path / "sspsygene_website_int"
    for site in (dev, prod, internal):
        (site / "data" / "db").mkdir(parents=True)
    _write_configs(dev / "data" / "datasets", LABELS)

    monkeypatch.setattr(deploy, "DEV_PATH", str(dev))
    monkeypatch.setattr(deploy, "PROD_PATH", str(prod))
    monkeypatch.setattr(deploy, "INT_PATH", str(internal))
    monkeypatch.setattr(
        deploy,
        "INSTANCE_PATHS",
        {"dev": str(dev), "int": str(internal), "prod": str(prod)},
    )

    def fake_cmd(site_path: str, argv: list[str]) -> str:
        args = " ".join(shlex.quote(a) for a in argv)
        return (
            f"{shlex.quote(sys.executable)} -c "
            f"{shlex.quote('from processing.click.main import cli; cli()')} {args}"
        )

    monkeypatch.setattr(deploy, "_site_sspsygene_cmd", fake_cmd)

    return {
        "dev": dev,
        "prod": prod,
        "int": internal,
        "dev_main": dev / "data/db/sspsygene.db",
        "dev_meta": dev / "data/db/sspsygene-meta.db",
        "dev_overview": dev / "data/db/sspsygene-overview.db",
        "dev_datasets": dev / "data/datasets",
        "prod_main": prod / "data/db/sspsygene.db",
        "prod_meta": prod / "data/db/sspsygene-meta.db",
        "prod_overview": prod / "data/db/sspsygene-overview.db",
        "prod_db_dir": prod / "data/db",
        "int_main": internal / "data/db/sspsygene.db",
        "int_db_dir": internal / "data/db",
    }


def test_resolve_local_off_hive_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate an off-/hive host (e.g. a laptop) by pointing DEV_PATH/PROD_PATH
    # at absent dirs. This must be done explicitly rather than relying on the
    # host: the server-side `deploy --run-tests` suite runs ON psygene, where
    # the REAL /hive trees exist, so without these monkeypatches auto-detect
    # would (correctly) return local=True and this test would spuriously fail.
    monkeypatch.setattr(deploy, "DEV_PATH", str(tmp_path / "absent_dev"))
    monkeypatch.setattr(deploy, "PROD_PATH", str(tmp_path / "absent_prod"))
    assert _resolve_promote_local(None) is False
    with pytest.raises(DeployError, match="can't see the /hive trees"):
        _resolve_promote_local(True)


def test_resolve_auto_detects_local(hive: dict[str, Path]) -> None:
    assert _resolve_promote_local(None) is True
    assert _resolve_promote_local(True) is True
    assert _resolve_promote_local(False) is False


def test_promote_subsets_to_prod_and_swaps_all_three(
    hive: dict[str, Path]
) -> None:
    """The headline behaviour: prod gets the subset, not dev's superset, and
    the meta and overview DBs ride along verbatim."""
    _make_dataset_db(hive["dev_main"], LABELS)
    _make_simple_db(hive["dev_meta"], "combined_pvalue_groups", 3)
    _make_simple_db(hive["dev_overview"], "overview_matrix_expanded_columns", 7)
    _make_dataset_db(hive["prod_main"], {"public": ["dev", "prod"]})  # stale
    inode_before = hive["prod_main"].stat().st_ino

    run_promote_dev_to_prod(local=True)

    assert _tables(hive["dev_main"]) == {PUBLIC, EMBARGOED}
    assert _tables(hive["prod_main"]) == {PUBLIC}
    assert _count(hive["prod_meta"], "combined_pvalue_groups") == 3
    # The overview DB was never promoted before #225.
    assert _count(hive["prod_overview"], "overview_matrix_expanded_columns") == 7
    # Atomic swap → new inode (what the web app's inode-keyed reopen detects).
    assert hive["prod_main"].stat().st_ino != inode_before
    assert not list(hive["prod_db_dir"].glob("*.new"))


def test_promoted_prod_db_contains_no_trace_of_the_dev_only_dataset(
    hive: dict[str, Path]
) -> None:
    _make_dataset_db(hive["dev_main"], LABELS)
    run_promote_dev_to_prod(local=True, include_meta_analysis=False)

    conn = sqlite3.connect(f"file:{hive['prod_main']}?mode=ro", uri=True)
    try:
        objects = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert EMBARGOED not in objects
        assert f"{EMBARGOED}__gene" not in objects
        assert not conn.execute(
            "SELECT count(*) FROM central_gene_usage WHERE table_name = ?",
            (EMBARGOED,),
        ).fetchone()[0]
        names = conn.execute(
            "SELECT dataset_names FROM central_gene"
        ).fetchone()[0]
        assert EMBARGOED not in (names or "")
    finally:
        conn.close()


def test_promote_dev_to_int_is_the_mirror(hive: dict[str, Path]) -> None:
    """int is now a target of dev like prod is — it used to build its own tree,
    which is why an embargoed dataset in dev could reach prod unnoticed."""
    _make_dataset_db(hive["dev_main"], LABELS)
    run_promote_dev_to_int(local=True, include_meta_analysis=False)
    assert _tables(hive["int_main"]) == {PUBLIC}
    assert not list(hive["int_db_dir"].glob("*.new"))


def test_promote_refuses_missing_source(hive: dict[str, Path]) -> None:
    with pytest.raises(DeployError, match="Source main DB not found"):
        run_promote_dev_to_prod(local=True)


def test_promote_refuses_a_pre_225_source(hive: dict[str, Path]) -> None:
    """A DB with no dataset_destinations cannot have its contents attributed to
    a destination, so it must not be promotable at all."""
    _make_simple_db(hive["dev_main"], "data_tables", 9)
    with pytest.raises(DeployError, match="no readable `dataset_destinations`"):
        run_promote_dev_to_prod(local=True)


def test_promote_refuses_an_incomplete_source(hive: dict[str, Path]) -> None:
    """The old check was `count >= --min-data-tables`, which passes for any
    non-empty build including one that silently dropped half its datasets."""
    _make_dataset_db(hive["dev_main"], LABELS)
    conn = sqlite3.connect(hive["dev_main"])
    conn.execute("DELETE FROM data_tables WHERE table_name = ?", (PUBLIC,))
    conn.commit()
    conn.close()
    with pytest.raises(DeployError, match="missing 1 table"):
        run_promote_dev_to_prod(local=True)


def test_promote_refuses_when_nothing_is_labelled_for_the_destination(
    hive: dict[str, Path]
) -> None:
    _make_dataset_db(hive["dev_main"], {"public": ["dev"], "secret": ["dev"]})
    with pytest.raises(DeployError, match="labelled `deployTo"):
        run_promote_dev_to_prod(local=True)


def test_promote_aborts_and_leaves_prod_untouched_when_the_guard_fails(
    hive: dict[str, Path],
) -> None:
    """The abort path. dev's DB says the public dataset is prod-bound; the
    checkout's configs say it is dev-only. The guard catches the disagreement
    before anything is swapped."""
    _make_dataset_db(hive["dev_main"], LABELS)
    _make_dataset_db(hive["prod_main"], {"public": ["dev", "prod"]})
    prod_inode = hive["prod_main"].stat().st_ino
    _write_configs(hive["dev_datasets"], {"public": ["dev"], "secret": ["dev"]})

    with pytest.raises(DeployError) as excinfo:
        run_promote_dev_to_prod(local=True)

    message = str(excinfo.value)
    assert "PROMOTION ABORTED" in message
    assert "jbirgmei@gmail.com" in message
    # Prod is byte-for-byte what it was, and nothing was left staged.
    assert hive["prod_main"].stat().st_ino == prod_inode
    assert not list(hive["prod_db_dir"].glob("*.new"))


def test_promote_skips_meta_when_dev_lacks_it(hive: dict[str, Path]) -> None:
    _make_dataset_db(hive["dev_main"], LABELS)
    _make_simple_db(hive["prod_meta"], "combined_pvalue_groups", 1)

    run_promote_dev_to_prod(local=True, include_meta_analysis=True)

    assert _tables(hive["prod_main"]) == {PUBLIC}
    # Prod's stale meta is left untouched (warned, not failed).
    assert _count(hive["prod_meta"], "combined_pvalue_groups") == 1


def test_promote_main_only_when_no_meta_flag(hive: dict[str, Path]) -> None:
    _make_dataset_db(hive["dev_main"], LABELS)
    _make_simple_db(hive["dev_meta"], "combined_pvalue_groups", 4)
    _make_simple_db(hive["prod_meta"], "combined_pvalue_groups", 1)

    run_promote_dev_to_prod(local=True, include_meta_analysis=False)

    assert _tables(hive["prod_main"]) == {PUBLIC}
    assert _count(hive["prod_meta"], "combined_pvalue_groups") == 1


def test_promote_dry_run_writes_nothing(hive: dict[str, Path]) -> None:
    _make_dataset_db(hive["dev_main"], LABELS)
    _make_simple_db(hive["dev_meta"], "combined_pvalue_groups", 3)
    _make_dataset_db(hive["prod_main"], {"public": ["dev", "prod"]})
    prod_inode = hive["prod_main"].stat().st_ino

    run_promote_dev_to_prod(local=True, dry_run=True)

    assert hive["prod_main"].stat().st_ino == prod_inode
    assert not list(hive["prod_db_dir"].glob("*.new"))
    # The subset is not built either — dry-run returns before that step.
    assert not (hive["dev"] / "data/db/sspsygene-prod.db").exists()
