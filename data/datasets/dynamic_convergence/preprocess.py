"""Preprocess Garcia et al. 2026 META-DEG and zebrafish behavior tables.

Cleans the gene-symbol column in `Supplemental_Data_2(META_DEGs).csv` so
load-db sees canonical HGNC symbols. Two rescue families fire:

  * Tier A (excel_demangle): `1-Mar` ... `10-Mar` -> MARCHF*/MARCH*,
    `1-Sep` ... `12-Sep` -> SEPTIN*/SEPT*.
  * Tier C2 (strip_make_unique): R `make.unique` `.N` suffixes such as
    `MATR3.1`, `EMG1.1`, `KC877982.1` collapse only when safe (the
    un-suffixed form resolves and the suffixed form does not).

`HumanName_Baseline_behavior_pvalues.csv` has no mangled symbols today
but is copied through so config.yaml can point both tables at
`*_cleaned.csv` outputs symmetrically.

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing
import ...` resolves.

Inputs:
    Supplemental_Data_2(META_DEGs).csv
    HumanName_Baseline_behavior_pvalues.csv

Outputs (config.yaml reads these):
    Supplemental_Data_2(META_DEGs)_cleaned.csv
    HumanName_Baseline_behavior_pvalues_cleaned.csv
"""

import shutil
from pathlib import Path

import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, clean_gene_column

DIR = Path(__file__).resolve().parent

META_IN = DIR / "Supplemental_Data_2(META_DEGs).csv"
BEHAVIOR_IN = DIR / "HumanName_Baseline_behavior_pvalues.csv"
META_OUT = DIR / "Supplemental_Data_2(META_DEGs)_cleaned.csv"
BEHAVIOR_OUT = DIR / "HumanName_Baseline_behavior_pvalues_cleaned.csv"


def main() -> None:
    normalizer = GeneSymbolNormalizer.from_env()

    df = pd.read_csv(META_IN, dtype=str)
    cleaned, report = clean_gene_column(
        df,
        "MarkerName",
        species="human",
        normalizer=normalizer,
        excel_demangle=True,
        strip_make_unique=True,
    )
    print(report.summary())
    cleaned = cleaned.drop(columns=["_MarkerName_resolution"])
    cleaned.to_csv(META_OUT, index=False)
    print(f"Wrote {len(cleaned)} rows to {META_OUT}")

    # No mangled symbols in the zebrafish behavior table today; copy
    # through so the cleaned-output set is symmetric with config.yaml.
    shutil.copyfile(BEHAVIOR_IN, BEHAVIOR_OUT)
    print(f"Copied {BEHAVIOR_IN} -> {BEHAVIOR_OUT}")


if __name__ == "__main__":
    main()
