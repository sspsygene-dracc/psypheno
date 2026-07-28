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
import math
import sqlite3
import zipfile
from pathlib import Path

import pytest

from processing.config import get_sspsygene_config
from processing.sq_load import load_db, run_overview_matrix


def test_load_db_against_mini_dataset(mini_fixture: Path) -> None:
    config = get_sspsygene_config()
    out_db = config.out_db
    # The session fixture pre-creates db/ but no DB file should exist yet.
    assert not out_db.exists()

    # As of #176, load_db never computes the meta-analysis (it's a separate
    # command), so there are no hgnc_path / skip_meta_analysis params anymore.
    load_db(
        out_db,
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
        _assert_dataset_destinations(conn)
        _assert_central_gene_usage(conn)
    finally:
        conn.close()

    # The overview matrix (#222) is materialized into its own file by a separate
    # command chain (`overview-matrix`), reading the dataset DB just built.
    overview_db = config.overview_db
    assert not overview_db.exists()
    # min_groups=1 so the fixture's single-perturbation columns still materialize
    # (the default floor is 2; the fixture is too small to exercise it).
    run_overview_matrix(
        out_db,
        overview_db,
        no_index=True,
        min_groups=1,
        panel_gene_list=config.sspsygene_gene_list,
    )
    assert overview_db.exists()
    assert not overview_db.with_name(overview_db.name + ".new").exists()

    overview_conn = sqlite3.connect(overview_db)
    overview_conn.row_factory = sqlite3.Row
    try:
        _assert_overview_matrix(overview_conn)
    finally:
        overview_conn.close()


def _assert_dataset_destinations(conn: sqlite3.Connection) -> None:
    """`dataset_destinations` mirrors the fixtures' deployTo lists (#225)."""
    rows = {
        (r["dataset"], r["table_name"], r["destination"])
        for r in conn.execute("SELECT * FROM dataset_destinations")
    }
    assert rows == {
        ("mini_perturb", "mini_perturb_deg", "dev"),
        ("mini_perturb", "mini_perturb_deg", "prod"),
        ("mini_embargoed", "mini_embargoed_deg", "dev"),
    }

    # The destination set must agree exactly with data_tables — nothing
    # labelled that wasn't built, nothing built that wasn't labelled.
    labelled = {r[0] for r in conn.execute(
        "SELECT DISTINCT table_name FROM dataset_destinations"
    )}
    built = {r[0] for r in conn.execute("SELECT table_name FROM data_tables")}
    assert labelled == built

    # data_tables.dataset carries the dataset directory name (#225).
    assert {
        (r["table_name"], r["dataset"])
        for r in conn.execute("SELECT table_name, dataset FROM data_tables")
    } == {
        ("mini_perturb_deg", "mini_perturb"),
        ("mini_embargoed_deg", "mini_embargoed"),
    }


def _assert_central_gene_usage(conn: sqlite3.Connection) -> None:
    """`central_gene_usage` keeps the (gene, table, name) pairing that
    central_gene's flattened columns throw away (#225)."""
    usage = [
        (r["central_gene_id"], r["table_name"], r["species"], r["matched_name"])
        for r in conn.execute("SELECT * FROM central_gene_usage")
    ]
    assert usage, "central_gene_usage must not be empty"
    assert {u[1] for u in usage} == {"mini_perturb_deg", "mini_embargoed_deg"}
    assert {u[2] for u in usage} == {"mouse"}

    # Every usage row points at a central_gene row that survived `used`.
    gene_ids = {r[0] for r in conn.execute("SELECT id FROM central_gene")}
    assert {u[0] for u in usage} <= gene_ids

    # The flattened aggregates must be exactly re-derivable from the usage
    # rows — that equivalence is what lets subset-db recompute them.
    for row in conn.execute(
        "SELECT id, dataset_names, num_datasets FROM central_gene"
    ):
        derived = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT table_name FROM central_gene_usage "
                "WHERE central_gene_id = ?",
                (row["id"],),
            )
        }
        assert derived == set((row["dataset_names"] or "").split(",")) - {""}
        assert len(derived) == row["num_datasets"]

    # Genes reached only by the dev-only dataset exist and are attributable to
    # it alone — these are the rows a prod subset must drop entirely.
    pax6_only = conn.execute(
        "SELECT DISTINCT table_name FROM central_gene_usage "
        "WHERE matched_name = 'Pax6'"
    ).fetchall()
    assert [r[0] for r in pax6_only] == ["mini_embargoed_deg"]

    # Tcf4 is shared: a prod subset must keep it but shrink num_datasets.
    tcf4 = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT table_name FROM central_gene_usage "
            "WHERE matched_name = 'Tcf4'"
        )
    }
    assert tcf4 == {"mini_perturb_deg", "mini_embargoed_deg"}

    # The non-resolving stub paths (record_values / control_values) record
    # usages too, so manually-added entries drop cleanly when their table is
    # not a subset member.
    stub_names = {
        r[0]
        for r in conn.execute(
            "SELECT matched_name FROM central_gene_usage u "
            "JOIN central_gene g ON g.id = u.central_gene_id "
            "WHERE g.manually_added = 1"
        )
    }
    assert {"Gm99999", "NonTarget1", "Gm88888", "NonTarget2"} <= stub_names


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
        conn.execute("SELECT key, label FROM condition_types").fetchall()
    )
    assert disease_rows.get("asd") == "Autism"

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


def _assert_overview_matrix(conn: sqlite3.Connection) -> None:
    """The overview matrix is materialized into its own DB by the separate
    `overview-matrix` command (#222); `conn` is that overview DB.

    The fixture table is labeled `overview_matrix` + `overview_matrix_expand`
    with assay `perturbation`, which the fixture taxonomy maps to `perturb_seq`.
    Foxg1/Tbr1/Tcf4 are the perturbed genes; NonTarget1 is a control and must
    not appear. #213 removed the aggregated status columns — the rows are the
    perturbed genes across the expanded tables.
    """
    perturbed = {
        row["human_symbol"]
        for row in conn.execute("SELECT human_symbol FROM overview_matrix_genes")
    }
    assert perturbed == {"FOXG1", "TBR1", "TCF4"}

    # Expanded sub-columns are the *measured* gene column's values (mouse
    # symbols here), strongest first: Tcf4 is significant under two
    # perturbations, the rest under one.
    columns = [
        (row["column_value"], row["n_sig_groups"])
        for row in conn.execute(
            "SELECT column_value, n_sig_groups FROM overview_matrix_expanded_columns "
            "ORDER BY sort_rank"
        )
    ]
    assert columns == [("Tcf4", 2), ("Selenoo", 1), ("Mtap", 1), ("Gm99999", 1)]
    # Trp53's p-values never clear FDR 0.05, so it is not a column at all.
    assert not any(value == "Trp53" for value, _ in columns)

    cells = {
        (row["human_symbol"], row["column_value"]): row["value"]
        for row in conn.execute(
            "SELECT g.human_symbol, c.column_value, c.value "
            "FROM overview_matrix_expanded_cells c "
            "JOIN overview_matrix_genes g ON g.central_gene_id = c.central_gene_id"
        )
    }
    # -log10 of the most significant raw p for that (perturbed, measured) pair.
    assert cells[("TCF4", "Tcf4")] == round(-math.log10(7.1e-06), 3)
    assert cells[("TBR1", "Tcf4")] == round(-math.log10(0.00043), 3)
    # Selenoo's other row is under the NonTarget1 control, which is excluded.
    assert set(cells) == {
        ("FOXG1", "Selenoo"),
        ("FOXG1", "Mtap"),
        ("FOXG1", "Gm99999"),
        ("TBR1", "Tcf4"),
        ("TCF4", "Tcf4"),
    }

    info = dict(
        (row["key"], row["value"])
        for row in conn.execute("SELECT key, value FROM overview_matrix_info")
    )
    assert info["min_groups_floor"] == "1"


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
