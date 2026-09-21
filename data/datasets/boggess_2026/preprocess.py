"""Preprocess Boggess et al. 2026 CRISPRi + CaMPARI2 neuronal depolarization screen.

Sources:
  - Supplementary Data 8 (published as file S5 on Nature Communications):
    Gene-level phenotype scores for 389 hit genes across 12 screen conditions.
  - Source Data file (boggess_source_data.xlsx), Figures 6c and 6f:
    CROP-seq DEG results for TRIP12 and PTEN knockdowns.

Usage:
    python preprocess.py

Outputs:
    boggess_2026_screen.tsv
    boggess_2026_cropseq_deg.tsv
"""

from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent

S5_FILE = DIR / "boggess_s5.xlsx"
SOURCE_DATA_FILE = DIR / "boggess_source_data.xlsx"

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


def make_screen() -> None:
    df = pd.read_excel(S5_FILE)

    rows = []
    for cond_key, cond_label in CONDITIONS.items():
        chunk = df[["gene"]].copy()
        chunk["condition"] = cond_label
        chunk["phenotype_score"] = df[f"{cond_key}.phenotype_score"]
        chunk["log2_fold_change"] = df[f"{cond_key}.log_fold_change"]
        chunk["pvalue"] = df[f"{cond_key}.pvalue"]
        chunk["fdr"] = df[f"{cond_key}.fdr"]
        rows.append(chunk)

    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["gene", "condition"]).reset_index(drop=True)

    out.to_csv(DIR / "boggess_2026_screen.tsv", sep="\t", index=False)
    print(f"Wrote {len(out)} rows to boggess_2026_screen.tsv")


def make_cropseq_deg() -> None:
    xl = pd.ExcelFile(SOURCE_DATA_FILE)
    trip12 = pd.read_excel(xl, sheet_name="Figure6c")
    pten = pd.read_excel(xl, sheet_name="Figure6f")

    out = pd.concat([trip12, pten], ignore_index=True)
    out = out[["knockdown", "gene", "baseMean", "log2FoldChange", "lfcSE", "stat", "pvalue", "padj"]]
    # Drop rows without a resolvable gene symbol (DESeq2 outputs unnamed transcripts as "nan-INDEX")
    out = out[~out["gene"].astype(str).str.startswith("nan-")]
    # Drop self-referential rows where the knockdown gene is also the target gene
    out = out[out["knockdown"] != out["gene"]]
    out = out.sort_values(["knockdown", "padj"]).reset_index(drop=True)

    out.to_csv(DIR / "boggess_2026_cropseq_deg.tsv", sep="\t", index=False)
    print(f"Wrote {len(out)} rows to boggess_2026_cropseq_deg.tsv")


def main() -> None:
    make_screen()
    make_cropseq_deg()


if __name__ == "__main__":
    main()
