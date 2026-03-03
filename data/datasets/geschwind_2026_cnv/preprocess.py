"""
Preprocess Geschwind 2026 CNV DE results.

Reads all 45 sheets from Supp_table_3_-_DE_results.xlsx and produces a single
de_results.tsv with added `sheet` (first column) and `region_genes` (last column).

Usage:
    python preprocess.py
"""

import json
from pathlib import Path
from typing import cast

import pandas as pd

EXCEL_PATH = (
    Path.home()
    / "Downloads"
    / "41586_2025_10047_MOESM3_ESM"
    / "Supp_table_3_-_DE_results.xlsx"
)
GENE_LISTS_PATH = Path(__file__).parent / "cnv_gene_lists.json"
OUTPUT_PATH = Path(__file__).parent / "de_results.tsv"


def get_deletion_type(sheet_name: str) -> str:
    """Extract the deletion type prefix from a sheet name like '16p11del_025'."""
    # Split on last underscore that precedes a timepoint suffix
    for suffix in ("_025", "_050", "_075", "_100", "_all_timepoints"):
        if sheet_name.endswith(suffix):
            return sheet_name[: -len(suffix)]
    raise ValueError(f"Unexpected sheet name format: {sheet_name}")


def main() -> None:
    with open(GENE_LISTS_PATH) as f:
        gene_lists = json.load(f)

    # Build mapping from deletion type to comma-separated gene string
    # 16p11dup uses the same genes as 16p11del
    dup_genes = gene_lists["16p11del"]["genes"]
    gene_lists["16p11dup"]["genes"] = dup_genes

    region_genes_map: dict[str, str] = {}
    for key, entry in gene_lists.items():
        genes = entry["genes"]
        if isinstance(genes, list):
            region_genes_map[key] = ",".join(genes)
        elif genes == "same as 16p11del":
            region_genes_map[key] = ",".join(dup_genes)
        else:
            region_genes_map[key] = ""

    all_sheets = pd.read_excel(EXCEL_PATH, sheet_name=None, engine="openpyxl")
    print(f"Read {len(all_sheets)} sheets")

    frames: list[pd.DataFrame] = []
    for sheet_name, df in all_sheets.items():
        deletion_type = get_deletion_type(sheet_name)
        if deletion_type not in region_genes_map:
            raise ValueError(
                f"Unknown deletion type '{deletion_type}' from sheet '{sheet_name}'. "
                f"Known types: {list(region_genes_map.keys())}"
            )

        # Drop rows where hgnc_symbol is missing
        df = df.dropna(subset=["hgnc_symbol"])
        df = cast(pd.DataFrame, df[df["hgnc_symbol"].astype(str).str.strip() != ""])

        # Add sheet and region_genes columns
        df.insert(0, "sheet", sheet_name)
        df["region_genes"] = region_genes_map[deletion_type]

        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(OUTPUT_PATH, sep="\t", index=False)
    print(f"Wrote {len(combined)} rows to {OUTPUT_PATH}")
    print(f"Columns: {list(combined.columns)}")

    # Summary per deletion type
    for sheet_name in all_sheets:
        deletion_type = get_deletion_type(sheet_name)
        n = len(combined[combined["sheet"] == sheet_name])
        n_genes = (
            len(region_genes_map[deletion_type].split(","))
            if region_genes_map[deletion_type]
            else 0
        )
        print(f"  {sheet_name}: {n} rows, {n_genes} region genes")


if __name__ == "__main__":
    main()
