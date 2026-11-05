"""Mouse genes the HGNC homology report links to several human genes
(central_gene_table.resolve_multi_orthologs)."""

from pathlib import Path

from processing.central_gene_table import (
    CentralGeneTable,
    CentralGeneTableEntry,
    parse_alliance_best_orthologs,
)
from processing.types.mgi_accession_id import MGIAcessionID


def _human(row_id: int, symbol: str, hgnc: str) -> CentralGeneTableEntry:
    return CentralGeneTableEntry(
        row_id=row_id,
        human_symbol=symbol,
        human_entrez_gene=None,
        human_ensembl_gene=None,
        hgnc_id=hgnc,
        mouse_symbols=set(),
        mouse_mgi_accession_ids=set(),
        mouse_ensembl_genes=set(),
        human_synonyms=set(),
        mouse_synonyms=set(),
    )


def _table(mouse: dict[str, str]) -> CentralGeneTable:
    table = CentralGeneTable()
    for i, (symbol, hgnc) in enumerate(
        [
            ("PMCH", "HGNC:9109"),
            ("PMCHL1", "HGNC:9110"),
            ("NOMO1", "HGNC:30060"),
            ("NOMO2", "HGNC:22652"),
            ("AMY1A", "HGNC:474"),
            ("AMY2B", "HGNC:478"),
            ("FOO1", "HGNC:1"),
            ("FOO2", "HGNC:2"),
        ]
    ):
        table.entries.append(_human(i, symbol, hgnc))
    table._mouse_symbol_by_mgi = {MGIAcessionID(k): v for k, v in mouse.items()}
    return table


def test_best_match_wins_over_pseudogenes() -> None:
    table = _table({"MGI:1": "Pmch"})
    out = table.resolve_multi_orthologs(
        {MGIAcessionID("MGI:1"): {"HGNC:9109", "HGNC:9110"}},
        {"MGI:1": {"HGNC:9109"}},
    )
    assert out[MGIAcessionID("MGI:1")] == {"HGNC:9109"}


def test_a_tie_is_broken_by_the_same_symbol() -> None:
    table = _table({"MGI:2": "Nomo1"})
    out = table.resolve_multi_orthologs(
        {MGIAcessionID("MGI:2"): {"HGNC:30060", "HGNC:22652"}},
        {"MGI:2": {"HGNC:30060", "HGNC:22652"}},
    )
    assert out[MGIAcessionID("MGI:2")] == {"HGNC:30060"}


def test_the_documented_best_match_is_used_even_with_another_name() -> None:
    # Alliance's best match for mouse Amy1 is AMY2B, not AMY1A.
    table = _table({"MGI:3": "Amy1"})
    out = table.resolve_multi_orthologs(
        {MGIAcessionID("MGI:3"): {"HGNC:474", "HGNC:478"}},
        {"MGI:3": {"HGNC:478"}},
    )
    assert out[MGIAcessionID("MGI:3")] == {"HGNC:478"}


def test_without_a_best_or_same_symbol_match_the_gene_stays_mouse_only() -> None:
    table = _table({"MGI:4": "Bar"})
    out = table.resolve_multi_orthologs(
        {MGIAcessionID("MGI:4"): {"HGNC:1", "HGNC:2"}}, {}
    )
    assert out[MGIAcessionID("MGI:4")] == set()
    assert table.unresolved_orthologs[MGIAcessionID("MGI:4")] == {"HGNC:1", "HGNC:2"}


def test_one_to_one_pairs_are_untouched() -> None:
    table = _table({"MGI:5": "Pmch"})
    out = table.resolve_multi_orthologs({MGIAcessionID("MGI:5"): {"HGNC:9110"}}, {})
    assert out[MGIAcessionID("MGI:5")] == {"HGNC:9110"}


def test_parse_reads_both_orientations_and_needs_both_flags(tmp_path: Path) -> None:
    path = tmp_path / "ortho.tsv"
    header = (
        "Gene1ID\tGene1Symbol\tGene1SpeciesTaxonID\tGene1SpeciesName\tGene2ID\t"
        "Gene2Symbol\tGene2SpeciesTaxonID\tGene2SpeciesName\tAlgorithms\t"
        "AlgorithmsMatch\tOutOfAlgorithms\tIsBestScore\tIsBestRevScore\n"
    )
    rows = [
        "MGI:1\tPmch\tNCBITaxon:10090\tm\tHGNC:9109\tPMCH\tNCBITaxon:9606\th\ta\t10\t10\tYes\tYes\n",
        "MGI:1\tPmch\tNCBITaxon:10090\tm\tHGNC:9110\tPMCHL1\tNCBITaxon:9606\th\ta\t3\t10\tNo\tYes\n",
        "HGNC:30060\tNOMO1\tNCBITaxon:9606\th\tMGI:2\tNomo1\tNCBITaxon:10090\tm\ta\t9\t10\tYes\tYes\n",
    ]
    path.write_text("# comment\n" + header + "".join(rows))
    assert parse_alliance_best_orthologs(path) == {
        "MGI:1": {"HGNC:9109"},
        "MGI:2": {"HGNC:30060"},
    }
