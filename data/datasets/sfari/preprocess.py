"""Preprocess SFARI Gene human-genes export: resolve ensembl-id to symbols.

Reads `SFARI-Gene_genes_07-08-2025release_10-03-2025export.csv` and
converts the `ensembl-id` column from raw `ENSG…` IDs to human symbols
via the shared `clean_gene_column` cleaner with
`resolve_via_ensembl_map=True`. Where an ENSG has no known symbol mapping
the value is preserved verbatim and falls through to the
`non_symbol_ensembl_human` classifier. The original ENSG is kept in the
auto-generated `ensembl-id_raw` column for audit.

This is the only sfari CSV with ENSGs in a displayed column (the rest
hold pure symbols already), so the other inputs are not touched and the
config.yaml `in_path` for the other tables continues to point at their
original files.

Migration is part of #119: stored values are now symbols, so SQL
filters / sorts and any future export operate on the same value the user
sees, and the runtime ENSG → symbol resolver is no longer needed.

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing
import ...` resolves.

Inputs:
    SFARI-Gene_genes_07-08-2025release_10-03-2025export.csv

Outputs (config.yaml reads these):
    SFARI-Gene_genes_07-08-2025release_10-03-2025export_cleaned.csv
"""

from pathlib import Path

import pandas as pd

from processing.preprocessing import (
    EnsemblToSymbolMapper,
    GeneSymbolNormalizer,
    clean_gene_column,
)

DIR = Path(__file__).resolve().parent

IN_FILE = DIR / "SFARI-Gene_genes_07-08-2025release_10-03-2025export.csv"
OUT_FILE = DIR / "SFARI-Gene_genes_07-08-2025release_10-03-2025export_cleaned.csv"


def main() -> None:
    normalizer = GeneSymbolNormalizer.from_env()
    ensembl_mapper = EnsemblToSymbolMapper.from_env()

    df = pd.read_csv(IN_FILE, dtype=str)
    cleaned, report = clean_gene_column(
        df,
        "ensembl-id",
        species="human",
        normalizer=normalizer,
        ensembl_mapper=ensembl_mapper,
        resolve_via_ensembl_map=True,
    )
    print(report.summary())
    cleaned = cleaned.drop(columns=["_ensembl-id_resolution"])
    cleaned.to_csv(OUT_FILE, index=False)
    print(f"Wrote {len(cleaned)} rows to {OUT_FILE}")


if __name__ == "__main__":
    main()
