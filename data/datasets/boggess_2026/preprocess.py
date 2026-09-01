"""Preprocess Boggess et al. 2026 CRISPRi + CaMPARI2 neuronal depolarization screen.

Source: Supplementary Data 8 (published as file S5 on Nature Communications).
Contains gene-level phenotype scores for 389 hit genes across 12 screen conditions.

These are the genes that showed a significant effect (FDR < 10%) in the primary
glutamate-stimulation CRISPRi screen of 1,343 disease-associated genes in human
iPSC-derived glutamatergic neurons. The full 1,343-gene primary screen data is
not yet publicly available.

Usage:
    python preprocess.py

Output:
    boggess_2026_screen.tsv
"""

from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent

S5_FILE = DIR / "boggess_s5.xlsx"

# Conditions to include and their human-readable labels.
# Skipping replicate A/B (redundant with primary) and iPSC controls
# (undifferentiated cells, less relevant to neuronal phenotype).
CONDITIONS = {
    "glut.primary":          "Primary glutamate screen",
    "glut.secondary":        "Secondary glutamate screen",
    "kcl.secondary":         "KCl secondary screen",
    "ttx.secondary":         "TTX secondary screen",
    "coculture.spontaneous": "Co-culture spontaneous activity",
    "coculture.glut":        "Co-culture glutamate screen",
    "survival":              "Survival screen",
}


def main() -> None:
    df = pd.read_excel(S5_FILE)

    rows = []
    for cond_key, cond_label in CONDITIONS.items():
        chunk = df[["gene"]].copy()
        chunk["condition"] = cond_label
        chunk["phenotype_score"] = df[f"{cond_key}.phenotype_score"]
        chunk["log2_fold_change"] = df[f"{cond_key}.log_fold_change"]
        chunk["fdr"] = df[f"{cond_key}.fdr"]
        chunk["pvalue"] = df[f"{cond_key}.pvalue"]
        rows.append(chunk)

    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["gene", "condition"]).reset_index(drop=True)

    out.to_csv(DIR / "boggess_2026_screen.tsv", sep="\t", index=False)
    print(f"Wrote {len(out)} rows to boggess_2026_screen.tsv")


if __name__ == "__main__":
    main()
