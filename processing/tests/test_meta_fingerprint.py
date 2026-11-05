"""Meta-analysis input fingerprint: unchanged inputs re-stamp, changes rebuild.

Builds a tiny dataset DB on disk (the shape `load-db` writes, including
`data_tables.meta_input_hash` and `build_info`), runs `run_meta_analysis`
against it with R mocked out, and checks when the second run recomputes vs.
re-stamps the existing meta DB.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from processing.build_info import write_build_info
from processing.combined_pvalues import collection, fingerprint
from processing.combined_pvalues.data import GeneCombinedPvalues
from processing.combined_pvalues.fingerprint import table_content_hash
from processing.sq_load import run_meta_analysis
from processing.types.link_table import LinkTable


def _fake_r(pvalues, use_cache=True):  # noqa: ARG001 — signature of call_r_combine
    return {
        gid: GeneCombinedPvalues(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        for gid in pvalues.all_pvalues
    }


def _table(
    name: str,
    pvals: list[float],
    genes: list[int],
    *,
    effect: list[float] | None = None,
    assay: str = "expression",
) -> dict:
    data = pd.DataFrame({"id": list(range(len(pvals))), "pval": pvals})
    if effect is not None:
        data["lfc"] = effect
    link = LinkTable(
        central_gene_table_links=list(zip(range(len(genes)), genes)),
        gene_column_name="gene",
        link_table_name=f"{name}__gene",
        perturbed_or_target="target",
    )
    return {
        "name": name,
        "data": data,
        "link": link,
        "assay": assay,
        "effect": "lfc" if effect is not None else None,
    }


def _default_tables() -> list[dict]:
    return [
        _table("tbl_a", [0.01, 0.02, 0.5], [1, 2, 3], effect=[1.0, -1.0, 2.0]),
        _table("tbl_b", [0.03, 0.04], [1, 2]),
        _table("tbl_c", [0.2, 0.3], [2, 3], assay="behavior"),
    ]


def _genes() -> list[tuple[int, str, str | None, str]]:
    return [
        (1, "BRCA1", "HGNC:1100", "gene"),
        (2, "TP53", "HGNC:11998", "gene"),
        (3, "MYGENE", None, "gene"),
    ]


def build_main_db(
    path: Path,
    tables: list[dict] | None = None,
    genes: list[tuple[int, str, str | None, str]] | None = None,
    *,
    with_hash: bool = True,
) -> None:
    """Write a fresh dataset DB at `path` (atomically, like load-db)."""
    tables = _default_tables() if tables is None else tables
    genes = _genes() if genes is None else genes
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    hash_col = ", meta_input_hash TEXT" if with_hash else ""
    conn.execute(
        "CREATE TABLE data_tables (table_name TEXT, pvalue_column TEXT, "
        "link_tables TEXT, assay TEXT, condition TEXT, organism_key TEXT, "
        "effect_column TEXT, include_in_meta_analysis INTEGER NOT NULL DEFAULT 1"
        f"{hash_col})"
    )
    conn.execute(
        "CREATE TABLE central_gene (id INTEGER PRIMARY KEY, human_symbol TEXT, "
        "hgnc_id TEXT, kind TEXT NOT NULL DEFAULT 'gene')"
    )
    conn.executemany(
        "INSERT INTO central_gene (id, human_symbol, hgnc_id, kind) "
        "VALUES (?, ?, ?, ?)",
        genes,
    )
    for t in tables:
        t["data"].to_sql(t["name"], conn, index=False)
        t["link"].write_to_sqlite(conn)
        row = [
            t["name"],
            "pval",
            t["link"].get_meta_entry(),
            t["assay"],
            None,
            "human",
            t["effect"],
            1,
        ]
        if with_hash:
            row.append(
                table_content_hash(t["data"], [t["link"]], "pval", t["effect"])
            )
        conn.execute(
            f"INSERT INTO data_tables VALUES ({', '.join('?' * len(row))})", row
        )
    conn.commit()
    write_build_info(conn)
    conn.close()
    tmp.replace(path)


def meta_info(meta_db: Path) -> dict[str, str]:
    with sqlite3.connect(meta_db) as conn:
        return dict(conn.execute("SELECT key, value FROM meta_analysis_info"))


def main_uuid(main_db: Path) -> str:
    with sqlite3.connect(main_db) as conn:
        return conn.execute(
            "SELECT value FROM build_info WHERE key = 'build_uuid'"
        ).fetchone()[0]


class Run:
    """Runs run_meta_analysis with R mocked and the p-value scan spied on."""

    def __init__(self, tmp_path: Path):
        self.main_db = tmp_path / "s.db"
        self.meta_db = tmp_path / "s-meta.db"
        self.scans = 0

    def __call__(self, *, assays=frozenset({"expression"}), r=_fake_r, **kw):
        real = collection.collect_pvalues_for_tables

        def spy(*a, **k):
            self.scans += 1
            return real(*a, **k)

        self.scans = 0
        with patch(
            "processing.combined_pvalues.r_runner.call_r_combine", side_effect=r
        ), patch(
            "processing.combined_pvalues.runner.collect_pvalues_for_tables",
            side_effect=spy,
        ):
            run_meta_analysis(
                self.main_db,
                self.meta_db,
                deg_assays=set(assays) if assays is not None else None,
                **kw,
            )
        return self.scans


@pytest.fixture
def run(tmp_path: Path) -> Run:
    r = Run(tmp_path)
    build_main_db(r.main_db)
    return r


def test_first_run_builds_and_records_fingerprint(run: Run):
    assert run() == 6
    info = meta_info(run.meta_db)
    assert info["source_build_uuid"] == main_uuid(run.main_db)
    assert info["input_fingerprint"]
    assert "tbl_a" in info["input_fingerprint_detail"]


def test_unchanged_inputs_restamp_without_scanning(run: Run):
    run()
    first = meta_info(run.meta_db)
    with sqlite3.connect(run.meta_db) as conn:
        before = conn.execute(
            "SELECT * FROM gene_combined_pvalues_target ORDER BY central_gene_id"
        ).fetchall()

    # A new load-db with identical inputs: new build UUID, same content.
    build_main_db(run.main_db)
    assert main_uuid(run.main_db) != first["source_build_uuid"]
    assert run(r=AssertionError("R must not run on a re-stamp")) == 0

    second = meta_info(run.meta_db)
    assert second["source_build_uuid"] == main_uuid(run.main_db)
    assert second["input_fingerprint"] == first["input_fingerprint"]
    assert second["built_at"] == first["built_at"]
    assert "restamped_at" in second
    with sqlite3.connect(run.meta_db) as conn:
        after = conn.execute(
            "SELECT * FROM gene_combined_pvalues_target ORDER BY central_gene_id"
        ).fetchall()
    assert after == before
    # Group-writable regardless of umask (multi-user servers).
    assert stat.S_IMODE(os.stat(run.meta_db).st_mode) & 0o020
    assert not run.meta_db.with_name(run.meta_db.name + ".new").exists()


def test_restamp_is_group_writable_under_umask_022(run: Run):
    run()
    build_main_db(run.main_db)
    old = os.umask(0o022)
    try:
        assert run() == 0
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(run.meta_db).st_mode) == 0o664


def test_already_current_is_a_no_op(run: Run):
    run()
    ino = os.stat(run.meta_db).st_ino
    assert run() == 0
    assert os.stat(run.meta_db).st_ino == ino


def test_force_rebuilds(run: Run):
    run()
    assert run(force=True) == 6


def test_changed_pvalue_rebuilds(run: Run):
    run()
    tables = _default_tables()
    tables[0] = _table(
        "tbl_a", [0.01, 0.021, 0.5], [1, 2, 3], effect=[1.0, -1.0, 2.0]
    )
    build_main_db(run.main_db, tables)
    assert run() == 6


def test_changed_effect_sign_rebuilds(run: Run):
    run()
    tables = _default_tables()
    tables[0] = _table(
        "tbl_a", [0.01, 0.02, 0.5], [1, 2, 3], effect=[1.0, 1.0, 2.0]
    )
    build_main_db(run.main_db, tables)
    assert run() == 6


def test_changed_gene_link_rebuilds(run: Run):
    run()
    tables = _default_tables()
    tables[1] = _table("tbl_b", [0.03, 0.04], [1, 3])
    build_main_db(run.main_db, tables)
    assert run() == 6


def test_added_meta_table_rebuilds(run: Run):
    run()
    tables = _default_tables() + [_table("tbl_d", [0.05], [1])]
    build_main_db(run.main_db, tables)
    assert run() == 6


def test_change_to_non_meta_table_is_reused(run: Run):
    """tbl_c's assay is not in metaAnalysisAssays, so it can't move the result."""
    run()
    tables = _default_tables()
    tables[2] = _table("tbl_c", [0.9, 0.8], [1, 2], assay="behavior")
    build_main_db(run.main_db, tables)
    assert run() == 0


def test_assay_list_change_rebuilds(run: Run):
    run()
    assert run(assays={"expression", "behavior"}) == 6
    assert run(assays=None) == 6


def test_gene_symbol_change_rebuilds(run: Run):
    """Same ids, but gene 2 now means something else (flags / display)."""
    run()
    genes = _genes()
    genes[1] = (2, "TP53X", "HGNC:11998", "gene")
    build_main_db(run.main_db, genes=genes)
    assert run() == 6


def test_gene_kind_change_rebuilds(run: Run):
    run()
    genes = _genes()
    genes[2] = (3, "MYGENE", None, "control")
    build_main_db(run.main_db, genes=genes)
    assert run() == 6


def test_unlinked_gene_change_is_reused(run: Run):
    """A gene no meta table links to can't move the meta result."""
    run()
    build_main_db(run.main_db, genes=_genes() + [(99, "OTHER", None, "gene")])
    assert run() == 0


def test_code_version_change_rebuilds(run: Run):
    run()
    with patch.object(fingerprint, "code_version", return_value="different"):
        assert run() == 6


def test_reference_file_change_rebuilds(run: Run, tmp_path: Path):
    nimh = tmp_path / "nimh.csv"
    nimh.write_text("gene_symbol\nBRCA1\n")
    run(nimh_csv_path=nimh)
    assert run(nimh_csv_path=nimh) == 0
    nimh.write_text("gene_symbol\nTP53\n")
    assert run(nimh_csv_path=nimh) == 6


def test_no_index_change_rebuilds(run: Run):
    run()
    assert run(no_index=True) == 6


def test_source_without_hashes_always_rebuilds(run: Run):
    build_main_db(run.main_db, with_hash=False)
    run()
    assert "input_fingerprint" not in meta_info(run.meta_db)
    assert run() == 6


def test_incomplete_r_run_is_not_reused(run: Run):
    """R unavailable → no fingerprint recorded → the next run recomputes."""
    run(r=lambda pvalues, use_cache=True: None)
    assert "input_fingerprint" not in meta_info(run.meta_db)
    assert run() == 6
    assert "input_fingerprint" in meta_info(run.meta_db)


def test_table_content_hash_ignores_non_meta_columns():
    data = pd.DataFrame({"id": [0, 1], "pval": [0.1, 0.2], "note": ["a", "b"]})
    link = LinkTable([(0, 1), (1, 2)], "gene", "t__gene", "target")
    h1 = table_content_hash(data, [link], "pval", None)
    data2 = data.assign(note=["x", "y"])
    assert table_content_hash(data2, [link], "pval", None) == h1
    # Case-insensitive column match, as SQLite's is.
    data3 = data.rename(columns={"pval": "PVal"}).assign(PVal=[0.1, 0.3])
    assert table_content_hash(data3, [link], "pval", None) != h1
    assert table_content_hash(data, [link], None, None) is None
    # Link-pair order / duplicates / null genes don't matter (not stored).
    link2 = LinkTable([(1, 2), (0, 1), (0, 1), (1, None)], "gene", "t__gene", "target")
    assert table_content_hash(data, [link2], "pval", None) == h1
