"""Preprocess MGI phenotype annotations: resolve Marker Ensembl IDs to symbols.

Reads `MGI_PhenotypicAllele_annotated.rpt` (produced by
`add_phenotype_names.py`) and converts the `Marker Ensembl ID` column
from raw `ENSMUSG…` IDs to mouse symbols via `resolve_via_ensembl_map`.
Where an ENSMUSG has no known symbol mapping it is preserved verbatim
and falls through to the `non_symbol_ensembl_mouse` classifier. The
original ENSMUSG is kept in the auto-generated `Marker Ensembl ID_raw`
column for audit.

This migration is part of #119: stored values are now symbols, so SQL
filters / sorts and any future export operate on the same value the
user sees, and the runtime ENSG → symbol resolver is no longer needed.

Writes a sibling `preprocessing.yaml` (#150) that records every action
applied to the data.

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing
import ...` resolves.

Inputs:
    MGI_PhenotypicAllele_annotated.rpt  (from add_phenotype_names.py)

Outputs (config.yaml reads these):
    MGI_PhenotypicAllele_cleaned.rpt
    preprocessing.yaml   (provenance log)
"""

from pathlib import Path

from processing.preprocessing import (
    EnsemblToSymbolMapper,
    GeneSymbolNormalizer,
    Pipeline,
    Tracker,
)

DIR = Path(__file__).resolve().parent

IN_FILE = DIR / "MGI_PhenotypicAllele_annotated.rpt"
OUT_FILE = DIR / "MGI_PhenotypicAllele_cleaned.rpt"


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()
    ensembl_mapper = EnsemblToSymbolMapper.from_env()

    (
        Pipeline(
            OUT_FILE.name,
            tracker=tracker,
            normalizer=normalizer,
            ensembl_mapper=ensembl_mapper,
        )
        .read_tsv(IN_FILE)
        .clean_gene(
            "Marker Ensembl ID",
            species="mouse",
            resolve_via_ensembl_map=True,
        )
        .write_tsv(OUT_FILE)
        .run()
    )

    tracker.write(DIR / "preprocessing.yaml")


if __name__ == "__main__":
    main()
