"""Preprocess NCBI ClinVar gene-specific summary into a SSPsyGene table.

Downloads
https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/gene_specific_summary.txt
(refreshed weekly upstream) into the dataset directory and produces a clean
TSV with one row per gene and the per-gene clinical-variant counts requested
in https://github.com/sspsygene-dracc/psypheno/issues/4 (Stephan Sanders).

Source schema (tab-separated, two leading lines starting with `#`):
    #Overview of data in ClinVar by gene, dated <date>
    #Symbol  GeneID  Total_submissions  Total_alleles
    Submissions_reporting_this_gene
    Alleles_reported_Pathogenic_Likely_pathogenic  Gene_MIM_number
    Number_uncertain  Number_with_conflicts

Per the issue, we drop GeneID and Gene_MIM_number; keep only the six
clinical-summary counts plus the gene symbol. Missing-value placeholder in
the source is `-`, which we coerce to NaN at read time.

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing import …`
resolves.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from processing.preprocessing import GeneSymbolNormalizer, Pipeline, Tracker

DIR = Path(__file__).resolve().parent
SOURCE_URL = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/gene_specific_summary.txt"
)
RAW_FILE = DIR / "gene_specific_summary.txt"
OUT_FILE = DIR / "clinvar_gene_summary.tsv"


def download_if_missing(url: str, dest: Path) -> None:
    if dest.exists():
        return
    urllib.request.urlretrieve(url, dest)


def main() -> None:
    download_if_missing(SOURCE_URL, RAW_FILE)

    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    (
        Pipeline(OUT_FILE.name, tracker=tracker, normalizer=normalizer)
        .read_tsv(
            RAW_FILE,
            skiprows=1,
            header=0,
            na_values=["-"],
        )
        .rename({"#Symbol": "Symbol"})
        .dropna("Symbol")
        .drop_columns(["GeneID", "Gene_MIM_number"], errors="ignore")
        .clean_gene("Symbol", species="human", resolve_via_ensembl_map=False)
        .write_tsv(OUT_FILE)
        .run()
    )


if __name__ == "__main__":
    main()
