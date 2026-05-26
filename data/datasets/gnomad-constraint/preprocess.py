"""Preprocess gnomAD v4 per-gene constraint metrics for SSPsyGene.

Downloads the gnomAD v4.1 per-gene constraint TSV from the gnomAD public GCS
bucket, filters to one row per gene (MANE Select transcript; canonical fallback
for genes absent from MANE), renames the Ensembl gene-ID column to gene_id_raw
per the identifier-preference rule (HGNC symbol > ENSG), and writes a clean TSV
for the loader.

Source: Chen et al. 2024, Nature 625, 92–100. PMID 38057664.
Download page: https://gnomad.broadinstitute.org/downloads#v4-constraint

Input:  gnomad.v4.1.constraint_metrics.tsv  (downloaded if absent)
Output: gnomad_constraint.tsv
        gnomad_constraint.tsv.preprocessing.yaml  (auto-emitted sidecar)

Usage:
    python preprocess.py
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, Pipeline, Tracker

DIR = Path(__file__).resolve().parent

SOURCE_URL = (
    "https://storage.googleapis.com/gcp-public-data--gnomad/"
    "release/4.1/constraint/gnomad.v4.1.constraint_metrics.tsv"
)
RAW_FILE = DIR / "gnomad.v4.1.constraint_metrics.tsv"
OUT_FILE = DIR / "gnomad_constraint.tsv"


def _mane_or_canonical(df: pd.DataFrame) -> pd.Series:
    """Boolean mask: MANE Select row per gene; fall back to canonical for genes
    that have no MANE Select transcript in the gnomAD v4 catalog.

    Pipeline reads all columns as dtype=str, so booleans arrive as the literal
    strings "true" / "false" — compare against the string, not a Python bool.
    """
    is_mane = df["mane_select"] == "true"
    is_canonical = df["canonical"] == "true"
    gene_has_mane = is_mane.groupby(df["gene"]).transform("any").astype(bool)
    return is_mane | (~gene_has_mane & is_canonical)


def download_if_missing(url: str, dest: Path) -> None:
    if dest.exists():
        return
    print(f"Downloading {url} ...")
    urllib.request.urlretrieve(url, dest)


def main() -> None:
    download_if_missing(SOURCE_URL, RAW_FILE)

    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    (
        Pipeline(OUT_FILE.name, tracker=tracker, normalizer=normalizer)
        .read_tsv(RAW_FILE, na_values=["NA", ""])
        .filter_rows(
            _mane_or_canonical,
            description=(
                "Keep MANE Select transcript per gene; fall back to canonical "
                "for genes absent from the MANE catalog (one row per gene)"
            ),
        )
        .rename({"gene_id": "gene_id_raw"})
        .clean_gene("gene", species="human", resolve_via_ensembl_map=False)
        .write_tsv(OUT_FILE)
        .run()
    )


if __name__ == "__main__":
    main()
