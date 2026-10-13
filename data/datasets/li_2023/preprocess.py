"""Preprocess Li et al. 2023 CHOOSE brain organoid CRISPR KO DEG data.

Source:
  Supplementary Data 2: DEGs from CRISPR knockout of 36 ASD risk genes
  in human telencephalic brain organoids (scRNA-seq, 4-month-old),
  compared to non-targeting gRNA controls. Results separated by neural
  trajectory (excitatory = dorsal telencephalon; inhibitory = ventral
  telencephalon).
  Li et al. 2023, Nature 621:373, doi:10.1038/s41586-023-06473-y

Usage:
    python preprocess.py

Output:
    li_2023_deg.tsv
"""

from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent


def main() -> None:
    df = pd.read_csv(DIR / "li_suppl_data2.txt", sep="\t")

    df = df.rename(columns={
        "feature":     "gene",
        "gRNA":        "perturbed_gene",
        "p_val":       "pvalue",
        "avg_log2FC":  "log2FC",
        "pct.1":       "pct_perturbed",
        "pct.2":       "pct_control",
        "p_val_adj":   "padj",
    })

    col_order = [
        "perturbed_gene", "gene", "lineage",
        "log2FC", "pvalue", "padj",
        "pct_perturbed", "pct_control",
    ]
    df = df[col_order]
    df = df.sort_values(["perturbed_gene", "lineage", "padj"]).reset_index(drop=True)

    out = DIR / "li_2023_deg.tsv"
    df.to_csv(out, sep="\t", index=False)
    print(f"Wrote {len(df)} rows to {out.name}")


if __name__ == "__main__":
    main()
