"""Tests for processing.ensembl_symbol_table.compute_ensembl_to_symbol."""

from __future__ import annotations

import sqlite3
from typing import Iterator

import pytest

import processing.central_gene_table as cgt
from processing.central_gene_table import (
    CentralGeneTable,
    CentralGeneTableEntry,
)
from processing.ensembl_symbol_table import compute_ensembl_to_symbol
from processing.types.ensembl_gene import EnsemblGene


@pytest.fixture
def stub_central_gene_table() -> Iterator[CentralGeneTable]:
    """Seed `central_gene_table._CENTRAL_GENE_TABLE` with a hand-built
    instance so `compute_ensembl_to_symbol` doesn't try to construct one
    from real homology files. Restored to None after the test.
    """
    table = CentralGeneTable()
    prior = cgt._CENTRAL_GENE_TABLE
    cgt._CENTRAL_GENE_TABLE = table
    try:
        yield table
    finally:
        cgt._CENTRAL_GENE_TABLE = prior


def _entry(
    *,
    row_id: int,
    human_symbol: str | None = None,
    human_ensg: str | None = None,
    mouse_symbols: set[str] | None = None,
    mouse_ensgs: set[str] | None = None,
    used: bool = True,
) -> CentralGeneTableEntry:
    return CentralGeneTableEntry(
        row_id=row_id,
        human_symbol=human_symbol,
        human_entrez_gene=None,
        human_ensembl_gene=EnsemblGene(human_ensg) if human_ensg else None,
        hgnc_id=None,
        mouse_symbols=mouse_symbols or set(),
        mouse_mgi_accession_ids=set(),
        mouse_ensembl_genes=(
            {EnsemblGene(e) for e in mouse_ensgs} if mouse_ensgs else set()
        ),
        human_synonyms=set(),
        mouse_synonyms=set(),
        used=used,
    )


def test_compute_ensembl_to_symbol_human_and_mouse(
    stub_central_gene_table: CentralGeneTable,
) -> None:
    stub_central_gene_table.entries = [
        _entry(row_id=0, human_symbol="BRCA1", human_ensg="ENSG00000012048"),
        _entry(row_id=1, mouse_symbols={"Trp53"}, mouse_ensgs={"ENSMUSG00000059552"}),
        # Mouse entry with multiple symbols: lexicographically smallest wins.
        _entry(
            row_id=2,
            mouse_symbols={"Foo", "Aaaa"},
            mouse_ensgs={"ENSMUSG00000099999"},
        ),
    ]

    conn = sqlite3.connect(":memory:")
    try:
        compute_ensembl_to_symbol(conn, no_index=True)
        rows = conn.execute(
            "SELECT ensembl_id, symbol, central_gene_id, species "
            "FROM ensembl_to_symbol ORDER BY ensembl_id"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("ENSG00000012048", "BRCA1", 0, "human"),
        ("ENSMUSG00000059552", "Trp53", 1, "mouse"),
        ("ENSMUSG00000099999", "Aaaa", 2, "mouse"),
    ]


def test_compute_ensembl_to_symbol_skips_unused_and_symbolless(
    stub_central_gene_table: CentralGeneTable,
) -> None:
    stub_central_gene_table.entries = [
        # Unused: not part of any dataset, must be skipped.
        _entry(
            row_id=0,
            human_symbol="UNUSED",
            human_ensg="ENSG00000000001",
            used=False,
        ),
        # Has ENSG but no symbol: skipped (symbol is required for the mapping).
        _entry(row_id=1, human_symbol=None, human_ensg="ENSG00000000002"),
    ]

    conn = sqlite3.connect(":memory:")
    try:
        compute_ensembl_to_symbol(conn, no_index=True)
        rows = conn.execute("SELECT * FROM ensembl_to_symbol").fetchall()
    finally:
        conn.close()
    assert rows == []


def test_compute_ensembl_to_symbol_creates_index_unless_disabled(
    stub_central_gene_table: CentralGeneTable,
) -> None:
    stub_central_gene_table.entries = [
        _entry(row_id=0, human_symbol="BRCA1", human_ensg="ENSG00000012048"),
    ]
    conn = sqlite3.connect(":memory:")
    try:
        compute_ensembl_to_symbol(conn, no_index=False)
        idx_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='ensembl_to_symbol'"
        ).fetchall()
    finally:
        conn.close()
    assert ("idx_ensembl_to_symbol_central_gene_id",) in idx_rows
