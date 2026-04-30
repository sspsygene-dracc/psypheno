"""Preprocess MGI phenotype annotations: resolve Marker Ensembl IDs to symbols.

Reads `MGI_PhenotypicAllele_annotated.rpt` (produced by
`add_phenotype_names.py`) and converts the `Marker Ensembl ID` column from
raw `ENSMUSG…` IDs to mouse symbols via the shared `clean_gene_column`
cleaner with `resolve_via_ensembl_map=True`. Where an ENSMUSG has no
known symbol mapping it is preserved verbatim and falls through to the
`non_symbol_ensembl_mouse` classifier. The original ENSMUSG is kept in
the auto-generated `Marker Ensembl ID_raw` column for audit.

This migration is part of #119: stored values are now symbols, so SQL
filters / sorts and any future export operate on the same value the user
sees, and the runtime ENSG → symbol resolver is no longer needed.

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing
import ...` resolves.

Inputs:
    MGI_PhenotypicAllele_annotated.rpt  (from add_phenotype_names.py)

Outputs (config.yaml reads these):
    MGI_PhenotypicAllele_cleaned.rpt
"""

from pathlib import Path

import pandas as pd

from processing.preprocessing import (
    EnsemblToSymbolMapper,
    GeneSymbolNormalizer,
    clean_gene_column,
)

DIR = Path(__file__).resolve().parent

IN_FILE = DIR / "MGI_PhenotypicAllele_annotated.rpt"
OUT_FILE = DIR / "MGI_PhenotypicAllele_cleaned.rpt"


def main() -> None:
    normalizer = GeneSymbolNormalizer.from_env()
    ensembl_mapper = EnsemblToSymbolMapper.from_env()

    df = pd.read_csv(IN_FILE, sep="\t", dtype=str)
    cleaned, report = clean_gene_column(
        df,
        "Marker Ensembl ID",
        species="mouse",
        normalizer=normalizer,
        ensembl_mapper=ensembl_mapper,
        resolve_via_ensembl_map=True,
    )
    print(report.summary())
    cleaned = cleaned.drop(columns=["_Marker Ensembl ID_resolution"])
    cleaned.to_csv(OUT_FILE, sep="\t", index=False)
    print(f"Wrote {len(cleaned)} rows to {OUT_FILE}")


if __name__ == "__main__":
    main()
