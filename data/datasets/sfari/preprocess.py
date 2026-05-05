"""Preprocess SFARI Gene human-genes export: resolve ensembl-id to symbols.

Reads `SFARI-Gene_genes_07-08-2025release_10-03-2025export.csv` and
converts the `ensembl-id` column from raw `ENSG…` IDs to human symbols
via `resolve_via_ensembl_map`. Where an ENSG has no known symbol
mapping the value is preserved verbatim and falls through to the
`non_symbol_ensembl_human` classifier. The original ENSG is kept in
the auto-generated `ensembl-id_raw` column for audit.

This is the only sfari CSV with ENSGs in a displayed column (the rest
hold pure symbols already), so the other inputs are not touched and
the config.yaml `in_path` for the other tables continues to point at
their original files.

Migration is part of #119: stored values are now symbols, so SQL
filters / sorts and any future export operate on the same value the
user sees, and the runtime ENSG → symbol resolver is no longer needed.

Writes a sibling `preprocessing.yaml` (#150) that records every action
applied to the data.

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing
import ...` resolves.

Inputs:
    SFARI-Gene_genes_07-08-2025release_10-03-2025export.csv

Outputs (config.yaml reads these):
    SFARI-Gene_genes_07-08-2025release_10-03-2025export_cleaned.csv
    preprocessing.yaml   (provenance log)
"""

from pathlib import Path

from processing.preprocessing import (
    GeneSymbolNormalizer,
    Pipeline,
    Tracker,
)

DIR = Path(__file__).resolve().parent

IN_FILE = DIR / "SFARI-Gene_genes_07-08-2025release_10-03-2025export.csv"
OUT_FILE = DIR / "SFARI-Gene_genes_07-08-2025release_10-03-2025export_cleaned.csv"


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    (
        Pipeline(OUT_FILE.name, tracker=tracker, normalizer=normalizer)
        .read_csv(IN_FILE)
        .clean_gene("ensembl-id", species="human")
        .write_csv(OUT_FILE)
        .run()
    )

    tracker.write(DIR / "preprocessing.yaml")


if __name__ == "__main__":
    main()
