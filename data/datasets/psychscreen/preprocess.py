"""Preprocess Pratt et al. 2024 PsychSCREEN DEG tables.

Cleans the `gene` column in all four DEGcombined CSVs via the shared
cleaner from #120. Three rescue families fire across the files:

  * Tier C3 (split_symbol_ensg): 8 `<symbol>_ENSG...` composites such
    as `TBCE_ENSG00000284770`, `MATR3_ENSG00000015479`,
    `ARMCX5-GPRASP2_ENSG00000286237` resolve to their canonical symbol
    after stripping the trailing ENSG identifier.
  * Tier A (excel_demangle): classic-form `1-Mar` ... `11-Mar` ->
    MARCHF*; `1-Dec` -> DELEC1.
  * Tier C2 (strip_make_unique): R `make.unique` `.N` suffixes — the
    helper rescues only when the un-suffixed form resolves and the
    suffixed form does not, so GENCODE clones like `AC000058.1`
    correctly fall through to the Tier B silencer.

The Tier A and Tier C2 rescues are out of #140's literal scope but
are rolled in here so the four large CSVs are touched once. See the
commit message for #140 for the per-file rescue tallies.

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
    ("Age_DEGcombined.csv", "Age_DEGcombined_cleaned.csv"),
    ("ASD_DEGcombined.csv", "ASD_DEGcombined_cleaned.csv"),
    ("Bipolar_DEGcombined.csv", "Bipolar_DEGcombined_cleaned.csv"),
    ("Schizophrenia_DEGcombined.csv", "Schizophrenia_DEGcombined_cleaned.csv"),
]

MANUAL_ALIASES = {
    "QARS": "QARS1",
    "SARS": "SARS1",
}


def main() -> None:
    normalizer = GeneSymbolNormalizer.from_env()

    for in_name, out_name in JOBS:
        df = pd.read_csv(DIR / in_name, dtype=str)
        cleaned, report = clean_gene_column(
            df,
            "gene",
            species="human",
            normalizer=normalizer,
            excel_demangle=True,
            strip_make_unique=True,
            split_symbol_ensg=True,
            manual_aliases=MANUAL_ALIASES,
        )
        print(f"{in_name}: {report.summary()}")
        cleaned = cleaned.drop(columns=["_gene_resolution"])
        cleaned.to_csv(DIR / out_name, index=False)
        print(f"  wrote {len(cleaned)} rows to {out_name}")


if __name__ == "__main__":
    main()
