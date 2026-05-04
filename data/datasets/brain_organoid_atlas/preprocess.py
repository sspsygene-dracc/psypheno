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

`patient_list.tsv` has clean human gene symbols today (plus the
`not_available` / `none identified` placeholders that the load-db
`non_resolving.drop_values:` block orphans); it's copied through
unchanged so every input file is routed through preprocess.

Writes a sibling `preprocessing.yaml` (#150) recording every action
across the four cleaned tables and the copy_file step.

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing
import ...` resolves.
"""

from pathlib import Path

from processing.preprocessing import (
    GeneSymbolNormalizer,
    Pipeline,
    Tracker,
    copy_file,
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
                excel_demangle=True,
                strip_make_unique=True,
                manual_aliases=MANUAL_ALIASES,
            )
            .write_tsv(DIR / out_name)
            .run()
        )

    copy_file(
        DIR / "patient_list.tsv",
        DIR / "patient_list_cleaned.tsv",
        tracker=tracker,
    )

    tracker.write(DIR / "preprocessing.yaml")


if __name__ == "__main__":
    main()
