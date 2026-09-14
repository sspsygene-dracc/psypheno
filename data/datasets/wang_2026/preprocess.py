"""
Preprocess Wang et al. 2026 ASD protein-protein interaction network.

Source: Supplementary Table S1, sheet "ASD-PPI", Wang et al. 2026, Science
393, eady4523. DOI: 10.1126/science.ady4523

Wild-type ASD-PPI network: 1,881 high-confidence AP-MS interactions between
100 hcASD bait proteins and 1,074 unique interactors, all pre-filtered to
SAINT_BFDR ≤ 0.05 by the authors.

Dropped columns:
  Spec       — per-replicate spectral count string (e.g. "3|2|4"); AvgSpec retained
  ctrlCounts — per-replicate control spectral counts; not searchable in the UI

Usage:
    python preprocess.py
"""

from pathlib import Path

import pandas as pd

from processing.preprocessing import Pipeline, Tracker

DIR = Path(__file__).resolve().parent
INFILE = DIR / "science.ady4523_table_s1.xlsx"
OUTFILE = DIR / "wang_2026_ppi.tsv"

RENAME = {
    "Bait": "bait",
    "Interactor_uniprot": "interactor_uniprot",
    "Interactor": "interactor",
    "type": "interaction_type",
}

KEEP = [
    "bait",
    "interactor_uniprot",
    "interactor",
    "interaction_type",
    "SAINT_BFDR",
    "CompPASS_rank_WD",
    "AvgSpec",
    "NumReplicates",
    "is_gold_standard",
]


def main() -> None:
    tracker = Tracker()
    tracker.note_input(INFILE.name)

    raw = pd.read_excel(INFILE, sheet_name="ASD-PPI")
    # Excel export appends trailing unnamed/metadata columns after is_gold_standard
    raw = raw[["Bait", "Interactor_uniprot", "Interactor", "type",
               "SAINT_BFDR", "CompPASS_rank_WD", "Spec", "AvgSpec",
               "NumReplicates", "ctrlCounts", "is_gold_standard"]]

    (
        Pipeline("wang_2026_ppi.tsv", tracker=tracker)
        .from_dataframe(raw, label="science.ady4523_table_s1.xlsx:ASD-PPI")
        .drop_columns(["Spec", "ctrlCounts"])
        .rename(RENAME)
        .reorder(KEEP)
        .transform_column(
            "NumReplicates",
            lambda s: s.astype(int),
            description="Cast float NumReplicates to int",
        )
        .write_tsv(OUTFILE)
        .run()
    )
    print("Wrote wang_2026_ppi.tsv")


if __name__ == "__main__":
    main()
