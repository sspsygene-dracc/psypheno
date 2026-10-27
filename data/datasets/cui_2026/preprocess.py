"""Preprocess Cui et al. 2026 XPO7 LoF bulk RNA-seq DEG data.

Source:
  Supplementary Table 1, sheet "Fig3D_deseq__XPO7LoF".
  DESeq2 results for XPO7 loss-of-function vs. parental control neurons
  (XPO7+/- and XPO7-/-) at day 28, 42, and 56 of differentiation.
  Cui et al. 2026, Molecular Psychiatry 31:4995-5013,
  doi:10.1038/s41380-026-03587-3

  Pooled genotype comparisons only (het and ko); individual clone data excluded.

Output:
    cui_2026_deg.tsv
"""

from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent
ENSEMBL_TO_SYMBOL = DIR / "ensembl_to_symbol.tsv"
SOURCE_FILE = DIR / "cui_suppl_table_1.xlsx"
SHEET = "Fig3D_deseq__XPO7LoF"

# wk4 = day 28, wk6 = day 42, wk8 = day 56 post-neuronal induction
TIMEPOINTS = {
    "wk4": "day28",
    "wk6": "day42",
    "wk8": "day56",
}
GENOTYPES = {
    "het": "XPO7+/-",
    "ko": "XPO7-/-",
}


def main() -> None:
    df = pd.read_excel(SOURCE_FILE, sheet_name=SHEET)
    df = df.rename(columns={"Ensembl ID": "gene_ensembl"})

    # Build Ensembl → symbol map; strip version suffix (e.g. ENSG00000000003.15 → ENSG00000000003)
    ens_df = pd.read_csv(ENSEMBL_TO_SYMBOL, sep="\t")
    ens_df["ensembl"] = ens_df["gene_id"].str.split(".").str[0]
    ens_map = ens_df.set_index("ensembl")["gene_name"].to_dict()

    rows = []
    for wk, day in TIMEPOINTS.items():
        for geno_short, geno_label in GENOTYPES.items():
            sub = df[["gene_ensembl"]].copy()
            sub["perturbed_gene"] = "XPO7"
            sub["genotype"] = geno_label
            sub["time_point"] = day
            sub["log2FC_shrink"] = df[f"{wk}_{geno_short}_Log2FC_shrink"].values
            sub["stat"] = df[f"{wk}_{geno_short}_stat"].values
            sub["padj"] = df[f"{wk}_{geno_short}_P_adj"].values
            rows.append(sub)

    out = pd.concat(rows, ignore_index=True)

    out["gene"] = out["gene_ensembl"].map(ens_map)
    missing = out["gene"].isna().sum()

    out = out.dropna(subset=["gene"])
    out = out[["perturbed_gene", "gene", "gene_ensembl",
               "genotype", "time_point", "log2FC_shrink", "stat", "padj"]]
    out = out.sort_values(["genotype", "time_point", "padj"]).reset_index(drop=True)

    out_path = DIR / "cui_2026_deg.tsv"
    out.to_csv(out_path, sep="\t", index=False)
    print(f"Wrote {len(out)} rows to {out_path.name}")
    print(f"  Genotypes: {sorted(out['genotype'].unique())}")
    print(f"  Time points: {sorted(out['time_point'].unique())}")
    print(f"  Dropped {missing} rows with no HGNC symbol")


if __name__ == "__main__":
    main()
