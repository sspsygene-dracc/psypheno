"""Preprocess Zheng et al. 2024 4TF Perturb-seq DEG data.

Cleans Excel-mangled gene names (e.g. `3-Mar`, `9-Sep`) in the Gene
column of `deg.txt`. `clusterprop.txt` is currently unaffected — its
`guide` column holds CRISPR perturbation IDs, not raw gene symbols —
but is copied through in case future updates introduce mangled values
there.

Writes a sibling `preprocessing.yaml` that records every action for
downstream provenance (#150).

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
    preprocessing.yaml   (provenance log)
"""

from pathlib import Path

from processing.preprocessing import (
    GeneSymbolNormalizer,
    Pipeline,
    Tracker,
    copy_file,
)

DIR = Path(__file__).resolve().parent


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    (
        Pipeline("deg_cleaned.txt", tracker=tracker, normalizer=normalizer)
        .read_tsv(DIR / "deg.txt")
        .clean_gene("Gene", species="mouse")
        .write_tsv(DIR / "deg_cleaned.txt")
        .run()
    )

    # No mangled values in clusterprop.txt today — copy through unchanged so
    # the output set is symmetric with what config.yaml references.
    copy_file(
        DIR / "clusterprop.txt",
        DIR / "clusterprop_cleaned.txt",
        tracker=tracker,
    )

    tracker.write(DIR / "preprocessing.yaml")


if __name__ == "__main__":
    main()
