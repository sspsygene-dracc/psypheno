"""Preprocess Zheng et al. 2026 in vivo multiome Perturb-seq DEG data.

Reads Supplementary Table 3 (filtered_DE_padj0.05 sheet), drops the
safe-target control row (ST2), cleans the Perturbation column to bare
gene symbols, and writes the output TSV.

Usage:
    cd ~/code/psypheno
    conda activate sspsygene
    python data/datasets/zheng_2026/preprocess.py

Inputs:
    zheng_suppl_table3.xlsx  (Supplementary Table 3 from Zheng et al. 2026)

Outputs:
    zheng_2026_deg.tsv
"""

from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent
SOURCE = DIR / "zheng_suppl_table3.xlsx"
OUT = DIR / "zheng_2026_deg.tsv"

CONTROLS = {"ST1", "ST2", "NT1", "NT2"}


def main() -> None:
    df = pd.read_excel(SOURCE, sheet_name="filtered_DE_padj0.05", header=0)
    print(f"Loaded {len(df)} rows")

    # Clean perturbation labels: "conditionMef2c_g2" → "Mef2c"
    df["perturbation"] = (
        df["Perturbation"]
        .str.replace(r"^condition", "", regex=True)
        .str.replace(r"_g\d+$", "", regex=True)
    )

    # Drop safe-target and non-targeting controls
    mask = df["perturbation"].isin(CONTROLS)
    if mask.sum():
        print(f"Dropping {mask.sum()} control row(s): {df.loc[mask, 'perturbation'].tolist()}")
    df = df[~mask].reset_index(drop=True)

    df = df[["perturbation", "Gene", "logFC", "logCPM", "LR", "PValue", "padj", "CT"]]
    df = df.rename(columns={"CT": "cell_type"})

    df.to_csv(OUT, sep="\t", index=False)
    print(f"Wrote {len(df)} rows to {OUT.name}")


if __name__ == "__main__":
    main()
