"""End-to-end integration test for `sq_load.load_db` against the mini fixture.

Runs the full loader against the real homology files (resolved by the
session fixture in conftest.py) and the synthetic dataset under
`processing/tests/fixtures/mini-dataset/`. Asserts on the resulting DB:
data_tables row, dynamic table schema, link tables, central_gene rows,
ensembl_to_symbol, control vs gene `kind`, and the export blobs.

Skips meta-analysis (no R) and gene-descriptions (no NCBI GenBank file);
both are exercised by their own targeted tests.
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path

from processing.config import get_sspsygene_config
from processing.sq_load import load_db


def test_load_db_against_mini_dataset(mini_fixture: Path) -> None:
    config = get_sspsygene_config()
    out_db = config.out_db
    # The session fixture pre-creates db/ but no DB file should exist yet.
    assert not out_db.exists()

    load_db(
        out_db,
        config.tables_config.tables,
        assay_types=config.global_config.get("assayTypes", {}),
        disease_types=config.global_config.get("diseaseTypes", {}),
        organism_types=config.global_config.get("organismTypes", {}),
        skip_missing=False,
        hgnc_path=config.gene_map_config.hgnc_file,
        no_index=True,
        data_dir=config.base_dir,
        skip_gene_descriptions=True,
        skip_meta_analysis=True,
    )

    assert out_db.exists()
    # No leftover staging or sidecar files.
    assert not out_db.with_name(out_db.name + ".new").exists()
    assert not out_db.with_name(out_db.name + "-wal").exists()
    assert not out_db.with_name(out_db.name + "-shm").exists()

    conn = sqlite3.connect(out_db)
    conn.row_factory = sqlite3.Row
    try:
        _assert_data_tables_row(conn)
        _assert_dynamic_table(conn)
        _assert_link_tables(conn)
        _assert_central_gene_rows(conn)
        _assert_ensembl_to_symbol(conn)
        _assert_lookup_tables(conn)
        _assert_changelog(conn)
        _assert_export_files(conn)
    finally:
        conn.close()


def _assert_data_tables_row(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT * FROM data_tables WHERE table_name = ?", ("mini_perturb_deg",)
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]

    assert r["short_label"] == "mini_perturb_degs"
    assert r["medium_label"] == "Mini Perturb DEGs (test fixture)"
    assert r["gene_species"] == "mouse"
    assert r["organism"] == "Mus musculus (test fixture)"
    assert r["organism_key"] == "mouse"
    assert r["pvalue_column"] == "pvalue"
    assert r["fdr_column"] == "padj"
    assert r["effect_column"] == "logfc"

    # Publication block landed.
    assert r["publication_year"] == 2024
    assert r["publication_doi"] == "10.0000/test.0001"
    assert r["publication_pmid"] == "12345678"
    assert r["publication_first_author"] == "Jane Doe"
    assert r["publication_last_author"] == "John Roe"

    # Per the landmines section, force-decimal numeric columns must land in
    # `scalar_columns` — otherwise pandas would have inferred int64.
    scalar_cols = set(r["scalar_columns"].split(","))
    assert {"pvalue", "padj", "logfc"}.issubset(scalar_cols)

    # Gene-mapping links serialized as the 3-part "col:link:direction" string.
    # Link names in the DB are prefixed with the parent table name.
    link_specs = set(r["link_tables"].split(","))
    assert link_specs == {
        "gene:mini_perturb_deg__gene:target",
        "perturbation_gene:mini_perturb_deg__perturbation_gene:perturbed",
    }

    # Field labels JSON parses; merged from globals + per-table.
    field_labels = json.loads(r["field_labels"])
    assert field_labels.get("gene") == (
        "Mouse target gene whose expression was measured"
    )
    # `pvalue` came from globals.yaml.
    assert "Nominal" in field_labels.get("pvalue", "")

    # Preprocessing sidecar made it into the column.
    preprocessing = json.loads(r["preprocessing"])
    assert preprocessing["source_file"] == "deg.tsv"
    assert isinstance(preprocessing["actions"], list)
    assert preprocessing["actions"][0]["kind"] == "read_csv"


def _assert_dynamic_table(conn: sqlite3.Connection) -> None:
    cols = [
        r["name"]
        for r in conn.execute("PRAGMA table_info(mini_perturb_deg)").fetchall()
    ]
    # `id` is auto-injected by load_data_table.
    assert "id" in cols
    for c in ("gene", "perturbation_gene", "pvalue", "padj", "logfc"):
        assert c in cols

    # 8 rows seeded in deg.tsv → 8 rows here.
    (count,) = conn.execute(
        "SELECT COUNT(*) FROM mini_perturb_deg"
    ).fetchone()
    assert count == 8


def _assert_link_tables(conn: sqlite3.Connection) -> None:
    """Dataset has two gene_mappings → two link tables, prefixed by table name."""
    table_names = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'mini_perturb_deg__%'"
        ).fetchall()
    }
    assert table_names == {"mini_perturb_deg__gene", "mini_perturb_deg__perturbation_gene"}

    # The `gene` link table should have a row for every data row whose `gene`
    # column resolved (or was recorded) — that's all 8 rows since Gm99999 is
    # explicit `record_values`. The schema is (central_gene_id, id) WITHOUT
    # ROWID; use COUNT(DISTINCT id) to count source rows.
    (gene_count,) = conn.execute(
        "SELECT COUNT(DISTINCT id) FROM mini_perturb_deg__gene"
    ).fetchone()
    assert gene_count == 8

    # The `perturbation_gene` link table also covers all 8 rows; NonTarget1
    # is recorded as a control central_gene, so its row still gets a link.
    (pert_count,) = conn.execute(
        "SELECT COUNT(DISTINCT id) FROM mini_perturb_deg__perturbation_gene"
    ).fetchone()
    assert pert_count == 8


def _assert_central_gene_rows(conn: sqlite3.Connection) -> None:
    """Real homology covers Foxg1/Tbr1/Tcf4/Trp53/Selenoo/Mtap; Gm99999 lands
    as a manually-added stub; NonTarget1 lands as kind='control'."""

    def _row(symbol: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT mouse_symbols, kind, manually_added FROM central_gene "
            "WHERE mouse_symbols = ? OR mouse_symbols LIKE ? OR mouse_symbols LIKE ? "
            "OR mouse_symbols LIKE ?",
            (symbol, f"{symbol},%", f"%,{symbol}", f"%,{symbol},%"),
        ).fetchone()

    foxg1 = _row("Foxg1")
    assert foxg1 is not None and foxg1["kind"] == "gene"

    trp53 = _row("Trp53")
    assert trp53 is not None and trp53["kind"] == "gene"

    # NonTarget1 was a control_value: kind='control', manually_added.
    nontarget = _row("NonTarget1")
    assert nontarget is not None
    assert nontarget["kind"] == "control"
    assert bool(nontarget["manually_added"]) is True

    # Gm99999 was a record_value: kind='gene', manually_added.
    gm = _row("Gm99999")
    assert gm is not None
    assert gm["kind"] == "gene"
    assert bool(gm["manually_added"]) is True


def _assert_ensembl_to_symbol(conn: sqlite3.Connection) -> None:
    """The mouse symbols we use in the fixture have ENSMUSG IDs in the real
    Alliance homology, so ensembl_to_symbol must contain entries for them."""
    rows = conn.execute(
        "SELECT ensembl_id, symbol, species FROM ensembl_to_symbol "
        "WHERE symbol IN ('Foxg1', 'Trp53', 'Tbr1', 'Tcf4')"
    ).fetchall()
    by_symbol = {r["symbol"] for r in rows}
    # All four real mouse symbols should have at least one ENSMUSG mapping.
    assert {"Foxg1", "Trp53", "Tbr1", "Tcf4"}.issubset(by_symbol)
    for r in rows:
        assert r["species"] == "mouse"
        assert r["ensembl_id"].startswith("ENSMUSG")


def _assert_lookup_tables(conn: sqlite3.Connection) -> None:
    assay_rows = dict(conn.execute("SELECT key, label FROM assay_types").fetchall())
    assert assay_rows.get("perturbation") == "Perturbation Screen"

    disease_rows = dict(
        conn.execute("SELECT key, label FROM disease_types").fetchall()
    )
    assert disease_rows.get("asd") == "Autism Spectrum Disorder"

    org_rows = dict(
        conn.execute("SELECT key, label FROM organism_types").fetchall()
    )
    assert org_rows.get("mouse") == "Mouse"


def _assert_changelog(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT date, message FROM changelog_entries WHERE table_name = ?",
        ("mini_perturb_deg",),
    ).fetchall()
    assert {r["date"] for r in rows} == {"2025-10-01", "2026-01-15"}


def _assert_export_files(conn: sqlite3.Connection) -> None:
    paths = {
        r["path"]
        for r in conn.execute("SELECT path FROM export_files").fetchall()
    }
    assert "tables/mini_perturb_deg.tsv" in paths
    assert "metadata/mini_perturb_deg.yaml" in paths
    assert "preprocessing/mini_perturb_deg.yaml" in paths
    assert "manifest.tsv" in paths
    assert "ensembl_to_symbol.tsv" in paths
    assert "all-tables.zip" in paths

    tsv = conn.execute(
        "SELECT content FROM export_files WHERE path = ?",
        ("tables/mini_perturb_deg.tsv",),
    ).fetchone()[0].decode("utf-8")
    lines = tsv.splitlines()
    # `id` is internal-only (added after display_columns is computed), so the
    # exported TSV header is the original config columns.
    header_cols = lines[0].split("\t")
    assert header_cols == ["gene", "perturbation_gene", "pvalue", "padj", "logfc"]
    # 8 data rows → 9 lines (header + 8).
    assert len(lines) == 9

    zip_blob = conn.execute(
        "SELECT content FROM export_files WHERE path = ?", ("all-tables.zip",)
    ).fetchone()[0]
    with zipfile.ZipFile(io.BytesIO(zip_blob)) as zf:
        names = set(zf.namelist())
    assert "tables/mini_perturb_deg.tsv" in names
    assert "manifest.tsv" in names
    assert "all-tables.zip" not in names
