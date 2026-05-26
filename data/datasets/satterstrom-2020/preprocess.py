"""
Preprocess Satterstrom et al. 2020 Table S2 (Cell 180:568-584).

Reads the supplementary Excel file and produces two clean TSVs:
  results_autosomal.tsv  — 17,484 autosomal genes with TADA FDR q-values
  results_chrx.tsv       — 727 chrX genes with TDT and de novo PTV p-values

The 'gene' column in the Excel is an older RefSeq-based symbol; 'hugoGene'
is the current HGNC symbol. We rename hugoGene -> gene before clean_gene so
that the 761 genes whose symbols have changed (e.g. SUV420H1 -> KMT5B) are
resolved against the current HGNC namespace.

Usage:
    python preprocess.py
"""

from pathlib import Path

import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, Pipeline, Tracker

DIR = Path(__file__).resolve().parent
EXCEL = DIR / "1-s2.0-S0092867419313984-mmc2.xlsx"


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    autosomal_df = pd.read_excel(
        EXCEL, sheet_name="Autosomal", engine="openpyxl", dtype=str
    )
    tracker.note_input(EXCEL.name)

    (
        Pipeline("results_autosomal.tsv", tracker=tracker, normalizer=normalizer)
        .from_dataframe(autosomal_df, label="Autosomal sheet")
        .rename({"gene": "gene_refseq", "hugoGene": "gene"})
        .dropna(["gene"])
        # hugoGene == "." marks non-coding RNA / pseudogene entries with no
        # current HGNC symbol; drop these as they cannot link to a gene page.
        .filter_rows(lambda df: df["gene"] != ".", description="drop genes without a current HGNC symbol (hugoGene='.' in source)")
        .clean_gene(
            "gene",
            species="human",
            excel_demangle=True,
            strip_make_unique=True,
        )
        .write_tsv(DIR / "results_autosomal.tsv")
        .run()
    )

    chrx_df = pd.read_excel(
        EXCEL, sheet_name="ChrX", engine="openpyxl", dtype=str
    )

    (
        Pipeline("results_chrx.tsv", tracker=tracker, normalizer=normalizer)
        .from_dataframe(chrx_df, label="ChrX sheet")
        .rename({"gene": "gene_refseq", "hugoGene": "gene"})
        .dropna(["gene"])
        .clean_gene(
            "gene",
            species="human",
            excel_demangle=True,
            strip_make_unique=True,
        )
        .write_tsv(DIR / "results_chrx.tsv")
        .run()
    )


if __name__ == "__main__":
    main()
