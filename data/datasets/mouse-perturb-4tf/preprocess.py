"""Preprocess Zheng et al. 2024 4TF Perturb-seq DEG data.

Cleans Excel-mangled gene names (e.g. `3-Mar`, `9-Sep`) in the Gene
column of `deg.txt` using the shared `processing.preprocessing`
library. `clusterprop.txt` is currently unaffected — its `guide` column
holds CRISPR perturbation IDs, not raw gene symbols — but is copied
through in case future updates introduce mangled values there.

Usage:
    python preprocess.py

Run inside the `processing` venv so that `from processing.preprocessing
import ...` resolves.

Inputs:
    deg.txt
    clusterprop.txt

Outputs (config.yaml reads these):
    deg_cleaned.txt
    clusterprop_cleaned.txt
"""

import shutil
from pathlib import Path

import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, clean_gene_column

DIR = Path(__file__).resolve().parent

DEG_IN = DIR / "deg.txt"
CLUSTERPROP_IN = DIR / "clusterprop.txt"
DEG_OUT = DIR / "deg_cleaned.txt"
CLUSTERPROP_OUT = DIR / "clusterprop_cleaned.txt"


def main() -> None:
    normalizer = GeneSymbolNormalizer.from_env()

    df = pd.read_csv(DEG_IN, sep="\t", dtype=str)
    cleaned, report = clean_gene_column(
        df,
        "Gene",
        species="mouse",
        normalizer=normalizer,
        excel_demangle=True,
    )
    print(report.summary())
    # Drop the annotation column so load-db's column expectations stay unchanged.
    cleaned = cleaned.drop(columns=["_Gene_resolution"])
    cleaned.to_csv(DEG_OUT, sep="\t", index=False)
    print(f"Wrote {len(cleaned)} rows to {DEG_OUT}")

    # No mangled values in clusterprop.txt today — copy through unchanged so
    # the output set is symmetric with what config.yaml references.
    shutil.copyfile(CLUSTERPROP_IN, CLUSTERPROP_OUT)
    print(f"Copied {CLUSTERPROP_IN} -> {CLUSTERPROP_OUT}")


if __name__ == "__main__":
    main()
