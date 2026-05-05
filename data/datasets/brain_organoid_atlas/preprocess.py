"""Preprocess Wang et al. 2025 brain-organoid atlas tables.

Cleans every gene-name column referenced by config.yaml. Three rescue
families fire across the NEBULA DEG and S10/S11 tables:

  * Tier A (excel_demangle): `1-Mar` ... `11-Mar` -> MARCHF*; `1-Dec`
    -> DELEC1.
  * Tier C2 (strip_make_unique): R `make.unique` `.N` suffixes such as
    `MATR3.1`, `TBCE.1`, `HSPA14.1`. The helper rescues these only
    when the un-suffixed form resolves and the suffixed form does not.
  * Manual aliases (retired-with-known-successor): SARS -> SARS1,
    QARS -> QARS1, TAZ -> TAFAZZIN.

`patient_list.tsv` has clean human gene symbols today, plus a small
number of `not_available` / `none identified` placeholder rows on the
`Pathologic causative mutation` column. The placeholders are dropped
here via a tracked `filter_rows` step (count recorded in
preprocessing.yaml); the rest of the rows pass through unchanged.

Writes a sibling `preprocessing.yaml` (#150) recording every action
across the four cleaned tables and the copy_file step.

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing
import ...` resolves.
"""

from pathlib import Path

import pandas as pd

from processing.preprocessing import (
    GeneSymbolNormalizer,
    Pipeline,
    Tracker,
)


PATIENT_LIST_GENE_COLUMN = "Pathologic causative mutation"
PATIENT_LIST_PLACEHOLDERS = ["not_available", "none identified"]


def _non_placeholder_mutation(df: pd.DataFrame) -> pd.Series:
    return pd.Series(
        [v not in PATIENT_LIST_PLACEHOLDERS for v in df[PATIENT_LIST_GENE_COLUMN]],
        index=df.index,
    )

DIR = Path(__file__).resolve().parent

MANUAL_ALIASES = {
    "SARS": "SARS1",
    "QARS": "QARS1",
    "TAZ": "TAFAZZIN",
}

# (input_filename, gene_column, output_filename)
JOBS: list[tuple[str, str, str]] = [
    ("nebula_gene_0.05_FDR.txt", "gene_symbol", "nebula_gene_0.05_FDR_cleaned.txt"),
    ("nebula_gene_0.2_FDR.tsv", "gene_symbol", "nebula_gene_0.2_FDR_cleaned.tsv"),
    ("s10.tsv", "gene_symbol", "s10_cleaned.tsv"),
    ("Table_8_Selected_validate_genes.txt", "gene", "Table_8_Selected_validate_genes_cleaned.txt"),
]


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    for in_name, column, out_name in JOBS:
        (
            Pipeline(out_name, tracker=tracker, normalizer=normalizer)
            .read_tsv(DIR / in_name)
            .clean_gene(
                column,
                species="human",
                manual_aliases=MANUAL_ALIASES,
            )
            .write_tsv(DIR / out_name)
            .run()
        )

    # patient_list goes through a small pipeline so the placeholder-row
    # drop is tracked in preprocessing.yaml. The gene column is kept as-is
    # (no clean_gene step) — the values are pathogenic-mutation labels
    # already in canonical HGNC form, not raw symbols needing rescue.
    (
        Pipeline("patient_list_cleaned.tsv", tracker=tracker, normalizer=normalizer)
        .read_tsv(DIR / "patient_list.tsv")
        .filter_rows(
            _non_placeholder_mutation,
            description=(
                f"drop rows where {PATIENT_LIST_GENE_COLUMN!r} is a placeholder "
                f"({', '.join(PATIENT_LIST_PLACEHOLDERS)})"
            ),
        )
        .write_tsv(DIR / "patient_list_cleaned.tsv")
        .run()
    )


if __name__ == "__main__":
    main()
