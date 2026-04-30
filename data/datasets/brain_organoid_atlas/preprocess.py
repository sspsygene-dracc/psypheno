"""Preprocess Wang et al. 2025 brain-organoid atlas tables.

Cleans every gene-name column referenced by config.yaml using the
shared cleaner from #120. Three rescue families fire across the NEBULA
DEG and S10/S11 tables:

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

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing
import ...` resolves.
"""

import shutil
from pathlib import Path

import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, clean_gene_column

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
    normalizer = GeneSymbolNormalizer.from_env()

    for in_name, column, out_name in JOBS:
        df = pd.read_csv(DIR / in_name, sep="\t", dtype=str)
        cleaned, report = clean_gene_column(
            df,
            column,
            species="human",
            normalizer=normalizer,
            excel_demangle=True,
            strip_make_unique=True,
            manual_aliases=MANUAL_ALIASES,
        )
        print(f"{in_name}: {report.summary()}")
        cleaned = cleaned.drop(columns=[f"_{column}_resolution"])
        cleaned.to_csv(DIR / out_name, sep="\t", index=False)
        print(f"  wrote {len(cleaned)} rows to {out_name}")

    shutil.copyfile(DIR / "patient_list.tsv", DIR / "patient_list_cleaned.tsv")
    print("  copied patient_list.tsv -> patient_list_cleaned.tsv")


if __name__ == "__main__":
    main()
