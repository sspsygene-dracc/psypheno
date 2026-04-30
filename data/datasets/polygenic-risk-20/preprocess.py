"""Preprocess Deans et al. 2026 polygenic-risk-20 supplementary tables.

Cleans both gene-name columns in Supp_1_all.csv and Supp_2_all.csv via
the shared cleaner from #120:

  * Tier A (excel_demangle): ISO-date forms `2023-03-01` ... `2023-03-11`
    -> MARCHF*; `2023-09-01` ... `2023-09-12` -> SEPTIN*. Both files
    contain these in `target_gene`; #143's scope listed Supp_1 only,
    but Supp_2 has the same ISO-date set so the flag is enabled there
    too.
  * Tier C2 (strip_make_unique): R `make.unique` `.N` suffixes such as
    `MATR3.1`, `TBCE.1`. The helper rescues these only when the
    un-suffixed form resolves and the suffixed form does not, so
    GenBank composites like `KC877982.1` correctly pass through to
    Tier B's silencer.

`perturbed_gene` columns hold a small set of canonical CRISPR-target
symbols (no mangling today) but are routed through the cleaner for
symmetry.

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing
import ...` resolves.
"""

from pathlib import Path

import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, clean_gene_column

DIR = Path(__file__).resolve().parent

JOBS: list[tuple[str, str]] = [
    ("Supp_1_all.csv", "Supp_1_all_cleaned.csv"),
    ("Supp_2_all.csv", "Supp_2_all_cleaned.csv"),
]
GENE_COLUMNS = ("perturbed_gene", "target_gene")

MANUAL_ALIASES = {
    "NOV": "CCN3",
    "MUM1": "PWWP3A",
    "SARS": "SARS1",
    "QARS": "QARS1",
    "TAZ": "TAFAZZIN",
}


def main() -> None:
    normalizer = GeneSymbolNormalizer.from_env()

    for in_name, out_name in JOBS:
        df = pd.read_csv(DIR / in_name, dtype=str)
        for column in GENE_COLUMNS:
            df, report = clean_gene_column(
                df,
                column,
                species="human",
                normalizer=normalizer,
                excel_demangle=True,
                strip_make_unique=True,
                manual_aliases=MANUAL_ALIASES,
            )
            print(f"{in_name}: {report.summary()}")
            df = df.drop(columns=[f"_{column}_resolution"])
        df.to_csv(DIR / out_name, index=False)
        print(f"  wrote {len(df)} rows to {out_name}")


if __name__ == "__main__":
    main()
