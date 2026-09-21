"""Tests for the GENCODE / NCBI reference-loci index (#113 follow-up)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from processing.reference_loci import (
    STABLE_ID_BASE,
    STABLE_ID_SPACE,
    build_reference_loci_index,
    stable_row_id,
)


def _write_gtf(path: Path, genes: list[tuple[str, str, str]]) -> None:
    lines = ["##description: test\n"]
    for ensg, name, gene_type in genes:
        attrs = f'gene_id "{ensg}.3"; gene_type "{gene_type}"; gene_name "{name}";'
        lines.append(f"chr1\tHAVANA\tgene\t1\t2\t.\t+\t.\t{attrs}\n")
        # A transcript line for the same gene must be ignored.
        lines.append(f"chr1\tHAVANA\ttranscript\t1\t2\t.\t+\t.\t{attrs}\n")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.writelines(lines)


_NCBI_HEADER = (
    "#tax_id\tGeneID\tSymbol\tLocusTag\tSynonyms\tdbXrefs\tchromosome\t"
    "map_location\tdescription\ttype_of_gene\n"
)


def _write_gene_info(path: Path, rows: list[tuple[str, str, str]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(_NCBI_HEADER)
        for gene_id, symbol, xrefs in rows:
            f.write(
                f"9606\t{gene_id}\t{symbol}\t-\t-\t{xrefs}\tchr1\t1q1\tdesc\tncRNA\n"
            )
        # A non-human row must be skipped.
        f.write("10090\t999999\tMouseGene\t-\t-\t-\tchr1\t1\tdesc\tncRNA\n")


@pytest.fixture
def index(tmp_path: Path):
    _write_gtf(
        tmp_path / "gencode.gtf.gz",
        [
            ("ENSG00000012048", "BRCA1", "protein_coding"),  # HGNC knows it
            ("ENSG00000236106", "AC010729.2", "lncRNA"),
            ("ENSG00000999999", "BRCA1", "lncRNA"),  # name claimed by HGNC
        ],
    )
    _write_gene_info(
        tmp_path / "gene_info.gz",
        [
            ("672", "BRCA1", "HGNC:HGNC:1100"),          # HGNC knows it
            ("105372576", "LOC105372576", "Ensembl:ENSG00000236106"),  # merges
            ("100130345", "LOC100130345", "-"),          # NCBI-only
        ],
    )
    return build_reference_loci_index(
        gencode_paths=[tmp_path / "gencode.gtf.gz"],
        ncbi_gene_info_path=tmp_path / "gene_info.gz",
        hgnc_ensembl_ids={"ENSG00000012048"},
        hgnc_ids={"HGNC:1100"},
        hgnc_entrez_ids={672},
        claimed_names={"BRCA1"},
    )


def test_gencode_locus_is_reachable_by_name_and_ensg(index) -> None:
    by_name = index.get("AC010729.2")
    assert by_name is not None
    assert by_name.key == "ensg:ENSG00000236106"
    assert index.get("ENSG00000236106") is by_name


def test_hgnc_genes_are_not_indexed(index) -> None:
    """HGNC's own genes already resolve; a reference locus must never shadow
    one, or a row would link to two central genes."""
    assert index.get("BRCA1") is None
    assert index.get("ENSG00000012048") is None


def test_ncbi_row_merges_into_the_gencode_locus_it_names(index) -> None:
    """One locus, two catalogues: ClinVar's LOC symbol and a dataset's ENSG
    must reach the same gene, which is the identity a stub never had."""
    locus = index.get("LOC105372576")
    assert locus is not None
    assert locus.key == "ensg:ENSG00000236106"
    assert locus.entrez_id == 105372576
    assert locus is index.get("AC010729.2")


def test_ncbi_only_locus_is_keyed_by_entrez(index) -> None:
    locus = index.get("LOC100130345")
    assert locus is not None
    assert locus.key == "entrez:100130345"
    assert locus.ensembl_id is None


def test_missing_inputs_yield_an_empty_index(tmp_path: Path) -> None:
    """A fresh checkout without `pull-data` still builds — those values just
    fall back to stubs, as they did before."""
    index = build_reference_loci_index(
        gencode_paths=[tmp_path / "absent.gtf.gz"],
        ncbi_gene_info_path=tmp_path / "absent.gz",
        hgnc_ensembl_ids=set(),
        hgnc_ids=set(),
        hgnc_entrez_ids=set(),
        claimed_names=set(),
    )
    assert len(index) == 0
    assert index.get("anything") is None


def test_ambiguous_names_are_dropped(tmp_path: Path) -> None:
    _write_gtf(
        tmp_path / "g.gtf.gz",
        [("ENSG00000000001", "SHARED", "lncRNA"), ("ENSG00000000002", "SHARED", "lncRNA")],
    )
    index = build_reference_loci_index(
        gencode_paths=[tmp_path / "g.gtf.gz"],
        ncbi_gene_info_path=None,
        hgnc_ensembl_ids=set(),
        hgnc_ids=set(),
        hgnc_entrez_ids=set(),
        claimed_names=set(),
    )
    assert index.get("SHARED") is None
    # Each locus is still reachable by its own unambiguous ENSG.
    assert index.get("ENSG00000000001") is not None
    assert index.get("ENSG00000000002") is not None


def test_stable_row_id_is_deterministic_and_in_range() -> None:
    first = stable_row_id("ensg:ENSG00000236106")
    assert first == stable_row_id("ensg:ENSG00000236106")
    assert first != stable_row_id("ensg:ENSG00000236107")
    assert STABLE_ID_BASE <= first < STABLE_ID_BASE + STABLE_ID_SPACE
    # Must stay exactly representable as a float64 (JSON / JS on the web side).
    assert STABLE_ID_BASE + STABLE_ID_SPACE < 2**53


def test_loci_sharing_a_catalogue_name_display_distinctly(tmp_path: Path) -> None:
    """GENCODE names six rRNA genes `5_8S_rRNA`. Each is a separate locus
    reached by its own NCBI name, so all six must not display identically."""
    _write_gtf(
        tmp_path / "g.gtf.gz",
        [("ENSG00000000001", "5_8S_rRNA", "rRNA"), ("ENSG00000000002", "5_8S_rRNA", "rRNA")],
    )
    _write_gene_info(
        tmp_path / "gene_info.gz",
        [
            ("110467520", "LOC110467520", "Ensembl:ENSG00000000001"),
            ("110467521", "LOC110467521", "Ensembl:ENSG00000000002"),
        ],
    )
    index = build_reference_loci_index(
        gencode_paths=[tmp_path / "g.gtf.gz"],
        ncbi_gene_info_path=tmp_path / "gene_info.gz",
        hgnc_ensembl_ids=set(),
        hgnc_ids=set(),
        hgnc_entrez_ids=set(),
        claimed_names=set(),
    )
    first = index.get("LOC110467520")
    second = index.get("LOC110467521")
    assert first is not None and second is not None
    assert first.display == "ENSG00000000001"
    assert second.display == "ENSG00000000002"


def test_locus_whose_name_hgnc_gives_another_gene_displays_as_ensg(
    tmp_path: Path,
) -> None:
    """NCBI calls GeneID 105373170 `DISC2`; HGNC gives that name to a
    different gene. Showing two genes as DISC2 is worse than showing the
    ENSG, and the row still resolves by every name it came in under."""
    _write_gtf(tmp_path / "g.gtf.gz", [("ENSG00000223510", "DISC2", "lncRNA")])
    index = build_reference_loci_index(
        gencode_paths=[tmp_path / "g.gtf.gz"],
        ncbi_gene_info_path=None,
        hgnc_ensembl_ids=set(),
        hgnc_ids=set(),
        hgnc_entrez_ids=set(),
        claimed_names={"DISC2"},
    )
    locus = index.get("ENSG00000223510")
    assert locus is not None
    assert locus.display == "ENSG00000223510"
    # The claimed name never becomes a lookup key — that would link a row to
    # both genes.
    assert index.get("DISC2") is None
