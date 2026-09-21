"""Focused unit tests for the CentralGeneTable in-memory API.

These tests build a CentralGeneTable() instance directly so they don't
depend on the real homology files or on the module-level
`_CENTRAL_GENE_TABLE` cache. End-to-end coverage of `construct()` lives
in test_sq_load_integration.py.
"""

from __future__ import annotations

import pytest

from processing.central_gene_table import (
    CentralGeneTable,
    CentralGeneTableEntry,
)
from processing.types.ensembl_gene import EnsemblGene


def test_add_manual_human_entry_marks_used_and_kind_gene() -> None:
    table = CentralGeneTable()
    entry = table.add_manual_human_entry("FOOBAR", dataset="ds1")

    assert entry.human_symbol == "FOOBAR"
    assert entry.manually_added is True
    assert entry.used is True
    assert entry.kind == "gene"
    assert entry.dataset_names == {"ds1"}
    assert entry.used_human_names == {"FOOBAR"}
    assert table.entries[-1] is entry


def test_add_manual_mouse_entry_marks_used_and_kind_gene() -> None:
    table = CentralGeneTable()
    entry = table.add_manual_mouse_entry("Foobar", dataset="ds2")

    assert entry.mouse_symbols == {"Foobar"}
    assert entry.human_symbol is None
    assert entry.manually_added is True
    assert entry.used is True
    assert entry.kind == "gene"
    assert entry.used_mouse_names == {"Foobar"}


def test_add_manual_entry_supports_kind_control() -> None:
    table = CentralGeneTable()
    entry = table.add_manual_human_entry(
        "NonTarget1", dataset="perturb1", kind="control"
    )
    assert entry.kind == "control"
    # Manually-added control still counts as used so the link table can
    # reference it.
    assert entry.used is True


def test_add_species_entry_dispatches_by_species() -> None:
    table = CentralGeneTable()
    h = table.add_species_entry("human", "BRCA1", dataset="d")
    m = table.add_species_entry("mouse", "Brca1", dataset="d")
    assert h.human_symbol == "BRCA1" and h.mouse_symbols == set()
    assert m.mouse_symbols == {"Brca1"} and m.human_symbol is None


def test_add_species_entry_invalid_species() -> None:
    table = CentralGeneTable()
    with pytest.raises(ValueError, match="Invalid species"):
        table.add_species_entry("zebrafish", "drd2", dataset="d")  # type: ignore[arg-type]


def test_get_human_map_includes_symbol_synonyms_and_ensembl() -> None:
    table = CentralGeneTable()
    table.entries.append(
        CentralGeneTableEntry(
            row_id=0,
            human_symbol="FOO",
            human_entrez_gene=None,
            human_ensembl_gene=EnsemblGene("ENSG00000111111"),
            hgnc_id="HGNC:1",
            mouse_symbols=set(),
            mouse_mgi_accession_ids=set(),
            mouse_ensembl_genes=set(),
            human_synonyms={"FOO_OLD"},
            mouse_synonyms=set(),
        )
    )

    m = table.get_human_map()
    assert "FOO" in m
    assert "FOO_OLD" in m
    assert "ENSG00000111111" in m
    # Cached on the instance so a second call is a dict identity hit.
    assert table.get_human_map() is m


def test_get_mouse_map_includes_symbol_synonyms_and_ensembl() -> None:
    table = CentralGeneTable()
    table.entries.append(
        CentralGeneTableEntry(
            row_id=0,
            human_symbol=None,
            human_entrez_gene=None,
            human_ensembl_gene=None,
            hgnc_id=None,
            mouse_symbols={"Foo"},
            mouse_mgi_accession_ids=set(),
            mouse_ensembl_genes={EnsemblGene("ENSMUSG00000022222")},
            human_synonyms=set(),
            mouse_synonyms={"foo_alt"},
        )
    )

    m = table.get_mouse_map()
    assert "Foo" in m
    assert "foo_alt" in m
    assert "ENSMUSG00000022222" in m


def test_get_species_map_dispatches_and_rejects_unknown() -> None:
    table = CentralGeneTable()
    table.add_manual_human_entry("BAR", dataset="d")
    table.add_manual_mouse_entry("Baz", dataset="d")

    assert "BAR" in table.get_species_map("human")
    assert "Baz" in table.get_species_map("mouse")
    with pytest.raises(ValueError, match="Invalid species"):
        table.get_species_map("zebrafish")  # type: ignore[arg-type]


def test_add_used_name_validates_species() -> None:
    entry = CentralGeneTableEntry(
        row_id=0,
        human_symbol="X",
        human_entrez_gene=None,
        human_ensembl_gene=None,
        hgnc_id=None,
        mouse_symbols=set(),
        mouse_mgi_accession_ids=set(),
        mouse_ensembl_genes=set(),
        human_synonyms=set(),
        mouse_synonyms=set(),
    )
    entry.add_used_name("human", "X", "ds1")
    assert entry.used is True
    assert entry.dataset_names == {"ds1"}
    assert entry.used_human_names == {"X"}

    with pytest.raises(ValueError, match="Invalid species"):
        entry.add_used_name("zebrafish", "X", "ds1")  # type: ignore[arg-type]


def test_stub_row_ids_survive_a_rebuild_with_different_load_order() -> None:
    """The bug this fixes: stub row_ids used to be `len(entries)`, so one new
    stub early in the build renumbered every stub after it — and the meta /
    overview DBs, which store central_gene ids and are rebuilt on their own
    cadence, then pointed at different genes."""
    first = CentralGeneTable()
    for symbol in ("AAA", "BBB", "CCC"):
        first.add_manual_human_entry(symbol, dataset="ds1")
    before = {e.human_symbol: e.row_id for e in first.entries}

    # Next build: a new stub lands first and the rest arrive in another order.
    second = CentralGeneTable()
    for symbol in ("NEW", "CCC", "AAA", "BBB"):
        second.add_manual_human_entry(symbol, dataset="ds1")
    after = {e.human_symbol: e.row_id for e in second.entries}

    assert {s: after[s] for s in before} == before


def test_stub_row_ids_are_species_scoped_and_unique() -> None:
    table = CentralGeneTable()
    human = table.add_manual_human_entry("FOO", dataset="ds")
    mouse = table.add_manual_mouse_entry("FOO", dataset="ds")
    assert human.row_id != mouse.row_id


def test_reference_entry_is_shared_and_not_manually_added() -> None:
    """A reference locus is one gene however a dataset spells it — the
    cross-dataset identity a per-value stub never had."""
    from processing.reference_loci import ReferenceLociIndex, ReferenceLocus

    locus = ReferenceLocus(
        key="ensg:ENSG00000236106",
        display="AC010729.2",
        ensembl_id="ENSG00000236106",
        entrez_id=105372576,
        names={"AC010729.2", "ENSG00000236106", "LOC105372576"},
    )
    table = CentralGeneTable()
    table.reference_loci = ReferenceLociIndex(
        by_name={name: locus for name in locus.names}
    )

    entry = table.add_reference_entry("LOC105372576", dataset="clinvar")
    assert entry is not None
    assert entry.manually_added is False
    assert entry.human_symbol == "AC010729.2"
    assert entry.human_ensembl_gene == EnsemblGene("ENSG00000236106")
    assert entry.human_entrez_gene is not None
    assert entry.human_entrez_gene.entrez_id == 105372576
    # Reachable under every name of the locus, so the next dataset finds it.
    assert set(table.get_human_map()) >= locus.names
    assert table.get_human_map()["ENSG00000236106"] == [entry]
    assert table.add_reference_entry("NOT_A_LOCUS", dataset="ds") is None
