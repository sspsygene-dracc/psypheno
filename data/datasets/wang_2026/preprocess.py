"""
Preprocess Wang et al. 2026 ASD protein-protein interaction network.

Source: Wang et al. 2026, Science 393, eady4523.
DOI: 10.1126/science.ady4523

Outputs two tables:

1. wang_2026_ppi.tsv — Wild-type ASD-PPI network (Table S1, sheet "ASD-PPI")
   1,881 high-confidence AP-MS interactions between 100 hcASD bait proteins
   and 1,074 unique interactors, all pre-filtered to SAINT_BFDR ≤ 0.05.
   Dropped: Spec (pipe-separated per-replicate string), ctrlCounts (same).

2. wang_2026_mut_ppi.tsv — Mutant differential PPI network (Table S6, sheet
   "ASDmut-PPI"). 1,065 rows showing interaction changes (mutant vs. WT) for
   54 patient-derived missense mutations across 30 hcASD bait proteins.
   Dropped: issue column (log2FC = ±8 convention communicates edge cases
   directly); 5 completeMissing rows (no observations in either condition).

Usage:
    python preprocess.py
"""

from pathlib import Path

import pandas as pd

from processing.preprocessing import Pipeline, Tracker

DIR = Path(__file__).resolve().parent
S1 = DIR / "science.ady4523_table_s1.xlsx"
S6 = DIR / "science.ady4523_table_s6.xlsx"
OUT_WT = DIR / "wang_2026_ppi.tsv"
OUT_MUT = DIR / "wang_2026_mut_ppi.tsv"

# ── Wild-type table ───────────────────────────────────────────────────────────

RENAME_WT = {
    "Bait": "bait",
    "Interactor_uniprot": "interactor_uniprot",
    "Interactor": "interactor",
    "type": "interaction_type",
}

KEEP_WT = [
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

# ── Mutant table ──────────────────────────────────────────────────────────────

RENAME_MUT = {
    "Bait": "bait",
    "PreyGene": "prey_gene",
    "Protein": "prey_uniprot",
    "fdr.pooled.storey": "fdr_storey",
}

KEEP_MUT = [
    "bait",
    "mutant",
    "prey_gene",
    "prey_uniprot",
    "log2FC",
    "SE",
    "Tvalue",
    "DF",
    "pvalue",
    "fdr_storey",
    "change",
    "obsCountWT",
    "obsCountMut",
]


def _read_mut_sheet() -> pd.DataFrame:
    """Read ASDmut-PPI sheet, skipping leading comment rows (lines starting
    with '#'). Returns a clean DataFrame with proper column headers."""
    raw = pd.read_excel(S6, sheet_name="ASDmut-PPI", header=None)
    header_idx = next(
        i for i, row in raw.iterrows()
        if pd.notna(row[0]) and not str(row[0]).startswith("#")
    )
    df = raw.iloc[header_idx:].reset_index(drop=True)
    df.columns = df.iloc[0]
    df = df.iloc[1:].reset_index(drop=True)
    # Keep only the 14 named columns; trailing metadata columns are unnamed
    df = df[["Bait", "mutant", "PreyGene", "Protein", "log2FC", "SE",
             "Tvalue", "DF", "pvalue", "issue", "obsCountWT", "obsCountMut",
             "change", "fdr.pooled.storey"]]
    return df


def main() -> None:
    tracker = Tracker()

    # ── Wild-type ─────────────────────────────────────────────────────────────
    tracker.note_input(S1.name)
    raw_wt = pd.read_excel(S1, sheet_name="ASD-PPI")
    # Excel export appends trailing unnamed/metadata columns after is_gold_standard
    raw_wt = raw_wt[["Bait", "Interactor_uniprot", "Interactor", "type",
                     "SAINT_BFDR", "CompPASS_rank_WD", "Spec", "AvgSpec",
                     "NumReplicates", "ctrlCounts", "is_gold_standard"]]

    (
        Pipeline("wang_2026_ppi.tsv", tracker=tracker)
        .from_dataframe(raw_wt, label="science.ady4523_table_s1.xlsx:ASD-PPI")
        .drop_columns(["Spec", "ctrlCounts"])
        .rename(RENAME_WT)
        .reorder(KEEP_WT)
        .transform_column(
            "NumReplicates",
            lambda s: s.astype(int),
            description="Cast float NumReplicates to int",
        )
        .write_tsv(OUT_WT)
        .run()
    )
    print("Wrote wang_2026_ppi.tsv")

    # ── Mutant ────────────────────────────────────────────────────────────────
    tracker.note_input(S6.name)
    raw_mut = _read_mut_sheet()

    (
        Pipeline("wang_2026_mut_ppi.tsv", tracker=tracker)
        .from_dataframe(raw_mut, label="science.ady4523_table_s6.xlsx:ASDmut-PPI")
        .filter_rows(
            lambda df: df["issue"] != "completeMissing",
            description="Drop 5 completeMissing rows (no observations in either condition)",
        )
        .drop_columns("issue")
        .rename(RENAME_MUT)
        .transform_column(
            "bait",
            lambda s: s.replace({"IRFBPL": "IRF2BPL"}),
            description="Rename IRFBPL to current approved HGNC symbol IRF2BPL",
        )
        .reorder(KEEP_MUT)
        .write_tsv(OUT_MUT)
        .run()
    )
    print("Wrote wang_2026_mut_ppi.tsv")


if __name__ == "__main__":
    main()
