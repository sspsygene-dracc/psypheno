"""Preprocess Geschwind lab bulk RNA-seq DEG data from day-28 NGN2 iPSC neurons.

Source:
  Wide-format limma-voom DEG table provided by Jacqueline Martin (Geschwind lab, UCLA).
  40 autism/NDD gene perturbations vs. control in NGN2-directed iPSC-derived neurons,
  day 28 of differentiation. Unpublished SSPsyGene consortium data.

  File: DGE_allContrasts_allGenes.csv
  Columns: Gene (Ensembl ID), then 6 stats per KO: logFC, AveExpr, t, P.Value, adj.P.Val, B

Output:
    geschwind_2026_deg.tsv
"""

from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent

ENSEMBL_TO_SYMBOL = DIR / "ensembl_to_symbol.tsv"
SOURCE_FILE = DIR / "DGE_allContrasts_allGenes.csv"


def main() -> None:
    df = pd.read_csv(SOURCE_FILE)
    df = df.rename(columns={"Gene": "gene_ensembl"})

    # Build Ensembl → symbol map; strip version suffix (e.g. ENSG00000000003.15 → ENSG00000000003)
    ens_df = pd.read_csv(ENSEMBL_TO_SYMBOL, sep="\t")
    ens_df["ensembl"] = ens_df["gene_id"].str.split(".").str[0]
    ens_map = ens_df.set_index("ensembl")["gene_name"].to_dict()

    # Melt wide → long: one row per (perturbed_gene, target_gene)
    # Column pattern: {GENE}_vs_Control_{stat}
    stat_cols = [c for c in df.columns if c != "gene_ensembl"]
    ko_genes = sorted({c.rsplit("_vs_Control_", 1)[0] for c in stat_cols})

    rows = []
    for ko in ko_genes:
        sub = df[["gene_ensembl"]].copy()
        sub["perturbed_gene"] = ko
        sub["log2FC"] = df[f"{ko}_vs_Control_logFC"].values
        sub["avg_expr"] = df[f"{ko}_vs_Control_AveExpr"].values
        sub["t_stat"] = df[f"{ko}_vs_Control_t"].values
        sub["pvalue"] = df[f"{ko}_vs_Control_P.Value"].values
        sub["padj"] = df[f"{ko}_vs_Control_adj.P.Val"].values
        sub["B"] = df[f"{ko}_vs_Control_B"].values
        rows.append(sub)

    out = pd.concat(rows, ignore_index=True)

    # Map Ensembl IDs to HGNC symbols; keep raw Ensembl in gene_ensembl
    out["gene"] = out["gene_ensembl"].map(ens_map)
    missing = out["gene"].isna().sum()

    # Drop rows with no symbol — unannotated/novel Ensembl IDs (lncRNAs, pseudogenes, etc.)
    out = out.dropna(subset=["gene"])
    out = out[["perturbed_gene", "gene", "gene_ensembl",
               "log2FC", "pvalue", "padj", "avg_expr", "t_stat", "B"]]
    out = out.sort_values(["perturbed_gene", "padj"]).reset_index(drop=True)

    out_path = DIR / "geschwind_2026_deg.tsv"
    out.to_csv(out_path, sep="\t", index=False)
    print(f"Wrote {len(out)} rows to {out_path.name}")
    print(f"  {out['perturbed_gene'].nunique()} KO genes")
    print(f"  Dropped {missing} rows with no HGNC symbol for Ensembl ID")


if __name__ == "__main__":
    main()
