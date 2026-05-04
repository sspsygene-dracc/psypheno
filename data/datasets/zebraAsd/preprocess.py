"""Preprocess Mendes et al. 2023 zebrafish ASD behavioral screen.

The `Mutant_Experiment_Sample` column in `mmc5.txt` encodes the mutated
gene as the first underscore-separated token (e.g. `chd8_HOM_3`).
Downstream gene resolution treats this dataset as human-orthologue
symbols, so we:

  * upper-case the gene token (`chd8` -> `CHD8`); and
  * map the zebrafish-only `scn1lab` paralog onto its human ortholog
    `SCN1A` so the cross-species link is correct.

These two transformations used to live at load-db time as
`to_upper:` / `replace:` knobs. Both have been retired in favor of
explicit preprocessing.

Writes a sibling `preprocessing.yaml` (#150) recording the
transformation. This dataset doesn't go through `clean_gene_column`
(its gene is embedded in a compound column, not a standalone gene
column), so the only tracked action is the custom transform.

Usage:
    python preprocess.py
"""

from pathlib import Path

import pandas as pd

from processing.preprocessing import Pipeline, Tracker

DIR = Path(__file__).resolve().parent

IN_FILE = DIR / "1-s2.0-S2211124723002541-mmc5.txt"
OUT_FILE = DIR / "1-s2.0-S2211124723002541-mmc5_cleaned.txt"

# Zebrafish paralogs whose human ortholog has a different symbol.
ZEBRAFISH_TO_HUMAN_ORTHOLOG = {"SCN1LAB": "SCN1A"}


def transform_sample(value: str) -> str:
    parts = value.split("_", 1)
    gene = parts[0].upper()
    gene = ZEBRAFISH_TO_HUMAN_ORTHOLOG.get(gene, gene)
    return "_".join([gene, *parts[1:]])


def _transform_sample_column(s: pd.Series) -> pd.Series:
    return pd.Series([transform_sample(v) for v in s], index=s.index)


def main() -> None:
    tracker = Tracker()
    (
        Pipeline(OUT_FILE.name, tracker=tracker)
        .read_tsv(IN_FILE)
        .transform_column(
            "Mutant_Experiment_Sample",
            _transform_sample_column,
            description=(
                "split on '_', upper-case gene token, "
                "map SCN1LAB -> SCN1A (zebrafish paralog -> human ortholog)"
            ),
        )
        .write_tsv(OUT_FILE)
        .run()
    )
    tracker.write(DIR / "preprocessing.yaml")


if __name__ == "__main__":
    main()
