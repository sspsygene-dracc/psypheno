"""Preprocess Liang et al. 2026 TF KO DEG data from the CHOOSE-like system.

Source:
  CSV files provided directly by Jubao Duan (co-corresponding author).
  Each file contains Seurat FindMarkers DEG results for one (KO gene, cell
  type, time point) combination: RORB, MEF2C, or TCF4 KO in GABAergic or
  Glutamatergic neurons at 0hr, 1hr, or 6hr KCl stimulation.
  Liang et al. 2026, Science 392, eadw3949,
  doi:10.1126/science.adw3949

Output:
    liang_2026_ko_deg.tsv
"""

from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent

CELL_TYPE_MAP = {
    "GABA": "GABAergic",
    "glut": "Glutamatergic",
}


def main() -> None:
    src_dir = DIR / "Data_for_Brittney"
    rows = []

    for csv_file in sorted(src_dir.glob("*.csv")):
        # Filename pattern: {cell_type}_{time_point}_{perturbed_gene}.csv
        parts = csv_file.stem.split("_")
        cell_type_raw = parts[0]
        time_point = parts[1]
        perturbed_gene = parts[2]

        df = pd.read_csv(csv_file, index_col=0)
        df = df.rename(columns={
            "avg_log2FC":  "log2FC",
            "p_val":       "pvalue",
            "p_val_adj":   "padj",
            "pct.1":       "pct_perturbed",
            "pct.2":       "pct_control",
        })
        df.index.name = "gene"
        df = df.reset_index()

        df["perturbed_gene"] = perturbed_gene
        df["cell_type"] = CELL_TYPE_MAP[cell_type_raw]
        df["time_point"] = time_point

        rows.append(df)

    out = pd.concat(rows, ignore_index=True)
    out = out[[
        "perturbed_gene", "gene", "cell_type", "time_point",
        "log2FC", "pvalue", "padj", "pct_perturbed", "pct_control",
    ]]
    out = out.sort_values(
        ["perturbed_gene", "cell_type", "time_point", "padj"]
    ).reset_index(drop=True)

    out_path = DIR / "liang_2026_ko_deg.tsv"
    out.to_csv(out_path, sep="\t", index=False)
    print(f"Wrote {len(out)} rows to {out_path.name}")


if __name__ == "__main__":
    main()
