"""Tests for processing.exports.write_exports.

We hand-build a minimal SQLite DB that mirrors the schema produced by
sq_load (data_tables row + matching dynamic table + ensembl_to_symbol)
and assert the resulting BLOBs in `export_files`. Decouples this layer
from the full sq_load pipeline.
"""

from __future__ import annotations

import io
import json
import sqlite3
import time
import zipfile
from pathlib import Path

import yaml

from processing.exports import write_exports


_DATA_TABLES_DDL = """
CREATE TABLE data_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT,
    short_label TEXT,
    medium_label TEXT,
    long_label TEXT,
    description TEXT,
    gene_columns TEXT,
    gene_species TEXT,
    display_columns TEXT,
    scalar_columns TEXT,
    link_tables TEXT,
    links TEXT,
    categories TEXT,
    source TEXT,
    assay TEXT,
    disease TEXT,
    field_labels TEXT,
    organism TEXT,
    organism_key TEXT,
    publication_first_author TEXT,
    publication_last_author TEXT,
    publication_author_count INTEGER,
    publication_authors TEXT,
    publication_year INTEGER,
    publication_journal TEXT,
    publication_doi TEXT,
    publication_pmid TEXT,
    publication_sspsygene_grants TEXT,
    pvalue_column TEXT,
    fdr_column TEXT,
    effect_column TEXT,
    preprocessing TEXT
)
"""

_ENSEMBL_DDL = """
CREATE TABLE ensembl_to_symbol (
    ensembl_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    central_gene_id INTEGER NOT NULL,
    species TEXT NOT NULL
)
"""


def _seed_minimal_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_DATA_TABLES_DDL)
        conn.executescript(_ENSEMBL_DDL)

        conn.execute(
            """INSERT INTO data_tables (
                table_name, short_label, medium_label, long_label, description,
                gene_columns, gene_species, display_columns, scalar_columns,
                link_tables, links, categories, source, assay, disease,
                field_labels, organism, organism_key,
                publication_first_author, publication_last_author,
                publication_author_count, publication_authors, publication_year,
                publication_journal, publication_doi, publication_pmid,
                publication_sspsygene_grants,
                pvalue_column, fdr_column, effect_column, preprocessing
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "tiny_table",
                "tiny_short",
                "tiny_medium",
                "tiny_long",
                "A minimal hand-built fixture row.",
                "gene",
                "mouse",
                "id,gene,score",
                "score",
                "gene:gene:perturbed",
                json.dumps([{"url": "https://example.test", "label": "Example"}]),
                "test fixture",
                "Test fixture",
                "perturbation",
                "asd",
                json.dumps({"score": "Effect score"}),
                "Mus musculus (test fixture)",
                "mouse",
                "Doe",
                "Roe",
                2,
                json.dumps(["Doe", "Roe"]),
                2024,
                "Test Journal",
                "10.0/test.0001",
                "12345678",
                json.dumps(["R01HG000000"]),
                None,
                None,
                "score",
                json.dumps(
                    {
                        "generated": "2026-05-05T00:00:00Z",
                        "actions": [{"kind": "read_csv"}],
                    }
                ),
            ),
        )

        conn.executescript(
            "CREATE TABLE tiny_table (id INTEGER, gene TEXT, score REAL)"
        )
        conn.executemany(
            "INSERT INTO tiny_table (id, gene, score) VALUES (?, ?, ?)",
            [(0, "Foxg1", 1.5), (1, "Trp53", -0.8), (2, "ENSMUSG00000059552", 0.0)],
        )
        conn.execute(
            "INSERT INTO ensembl_to_symbol VALUES (?, ?, ?, ?)",
            ("ENSMUSG00000059552", "Trp53", 100, "mouse"),
        )
        conn.commit()
    finally:
        conn.close()


def test_write_exports_writes_expected_blobs(tmp_path: Path) -> None:
    db = tmp_path / "tiny.db"
    _seed_minimal_db(db)

    before = int(time.time())
    write_exports(db)
    after = int(time.time())

    conn = sqlite3.connect(db)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT path, content_type, content, size, last_modified "
            "FROM export_files ORDER BY path"
        ).fetchall()
    finally:
        conn.close()

    by_path = {r["path"]: r for r in rows}

    expected_paths = {
        "tables/tiny_table.tsv",
        "metadata/tiny_table.yaml",
        "preprocessing/tiny_table.yaml",
        "ensembl_to_symbol.tsv",
        "manifest.tsv",
        "README.txt",
        "all-tables.zip",
    }
    assert set(by_path) == expected_paths

    # Per-row sanity: size matches len(content), last_modified is in range.
    for r in rows:
        assert r["size"] == len(r["content"])
        assert before <= r["last_modified"] <= after

    # Content types map to the file extension.
    assert by_path["tables/tiny_table.tsv"]["content_type"].startswith(
        "text/tab-separated-values"
    )
    assert by_path["all-tables.zip"]["content_type"] == "application/zip"
    assert by_path["README.txt"]["content_type"].startswith("text/plain")
    assert by_path["metadata/tiny_table.yaml"]["content_type"].startswith(
        "application/x-yaml"
    )

    # The TSV blob has the display columns + ENSG → symbol substitution.
    tsv = by_path["tables/tiny_table.tsv"]["content"].decode("utf-8")
    lines = tsv.splitlines()
    assert lines[0] == "id\tgene\tscore"
    assert lines[1] == "0\tFoxg1\t1.5"
    # The third row's `gene` value was an ENSG; the export substitutes it.
    assert lines[3].split("\t")[1] == "Trp53"

    # Metadata YAML is a valid YAML doc with the expected keys.
    md = yaml.safe_load(by_path["metadata/tiny_table.yaml"]["content"])
    assert md["table"] == "tiny_table"
    assert md["short_label"] == "tiny_short"
    assert md["display_columns"] == ["id", "gene", "score"]
    assert md["publication"]["doi"] == "10.0/test.0001"

    # Preprocessing YAML round-trips the JSON we stored.
    pp = yaml.safe_load(by_path["preprocessing/tiny_table.yaml"]["content"])
    assert pp["actions"] == [{"kind": "read_csv"}]

    # Manifest has a header row + one data row.
    manifest = by_path["manifest.tsv"]["content"].decode("utf-8").splitlines()
    assert manifest[0].split("\t")[0] == "table_name"
    assert manifest[1].split("\t")[0] == "tiny_table"

    # ensembl_to_symbol.tsv mirrors the source table.
    ets = by_path["ensembl_to_symbol.tsv"]["content"].decode("utf-8").splitlines()
    assert ets[0] == "ensembl_id\tsymbol\tcentral_gene_id\tspecies"
    assert ets[1] == "ENSMUSG00000059552\tTrp53\t100\tmouse"

    # all-tables.zip is a valid zip containing the per-table blobs (but not
    # itself).
    zip_bytes = by_path["all-tables.zip"]["content"]
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
    assert "tables/tiny_table.tsv" in names
    assert "metadata/tiny_table.yaml" in names
    assert "manifest.tsv" in names
    assert "README.txt" in names
    assert "all-tables.zip" not in names


def test_write_exports_omits_preprocessing_when_null(tmp_path: Path) -> None:
    """Tables without a preprocessing JSON shouldn't get a preprocessing/*.yaml
    blob — the manifest's preprocessing_path column should be empty for them."""
    db = tmp_path / "tiny.db"
    _seed_minimal_db(db)

    # Null out the preprocessing column.
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE data_tables SET preprocessing = NULL WHERE table_name = ?",
            ("tiny_table",),
        )
        conn.commit()
    finally:
        conn.close()

    write_exports(db)

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT path FROM export_files").fetchall()
    finally:
        conn.close()

    paths = {r[0] for r in rows}
    assert "preprocessing/tiny_table.yaml" not in paths
    assert "tables/tiny_table.tsv" in paths
