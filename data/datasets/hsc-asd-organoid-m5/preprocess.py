"""
Preprocess Gordon et al. 2026 ASD organoid DE results.

Reads Supplementary Table 3 (45 sheets, one per perturbation x timepoint) and
Supplementary Table 12 (26 sheets, one per M5 transcription factor) from the
downloaded Excel files and produces two TSV files.

Both reads pass `dtype=str` so any Excel-mangled date cells (e.g. `1-Mar`,
`9-Sep`) survive as strings rather than being silently converted to
Timestamps. Each sheet's gene column is then routed through
`processing.preprocessing.clean_gene_column` with `excel_demangle=True` and
`strip_make_unique=True` to rescue the mangled values and the R `make.unique`
`.N`-suffixed values that #144 / #126 expose. Numeric columns become strings
on the way through and re-parse to numerics when the TSV is loaded
downstream.

Usage:
    python preprocess.py

Input files (place in this directory):
    Supp_table_3_-_DE_results.xlsx
    Supp_table_12_-_DE_targets_of_M5_TFs.xlsx

Output files:
    supplementary_table_3_DE_results.tsv
    supplementary_table_12_DE_targets_M5_TFs.tsv
"""

import json
from pathlib import Path
from typing import cast

import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, clean_gene_column

DIR = Path(__file__).resolve().parent

MANUAL_ALIASES = {
    "QARS": "QARS1",
    "SARS": "SARS1",
    "TAZ": "TAFAZZIN",
}

# Copied from geschwind_2026_cnv/cnv_gene_lists.json — manually curated gene lists
# for each ASD-associated CNV region, sourced from ClinGen, OMIM, and GeneReviews.
CNV_GENE_LISTS = DIR / "cnv_gene_lists.json"

SUPP3_EXCEL = DIR / "Supp_table_3_-_DE_results.xlsx"
SUPP12_EXCEL = DIR / "Supp_table_12_-_DE_targets_of_M5_TFs.xlsx"

SUPP3_OUT = DIR / "supplementary_table_3_DE_results.tsv"
SUPP12_OUT = DIR / "supplementary_table_12_DE_targets_M5_TFs.tsv"


def get_deletion_type(sheet_name: str) -> str:
    for suffix in ("_025", "_050", "_075", "_100", "_all_timepoints"):
        if sheet_name.endswith(suffix):
            return sheet_name[: -len(suffix)]
    raise ValueError(f"Unexpected sheet name format: {sheet_name}")


def get_organoid_age(sheet_name: str) -> str:
    for suffix, age in [
        ("_025", "25"),
        ("_050", "50"),
        ("_075", "75"),
        ("_100", "100"),
        ("_all_timepoints", "all timepoints"),
    ]:
        if sheet_name.endswith(suffix):
            return age
    raise ValueError(f"Unexpected sheet name format: {sheet_name}")


def build_region_genes_map() -> dict[str, str]:
    with open(CNV_GENE_LISTS) as f:
        gene_lists = json.load(f)

    dup_genes = gene_lists["16p11del"]["genes"]
    region_genes_map = {}
    for key, entry in gene_lists.items():
        genes = entry["genes"]
        if isinstance(genes, list):
            region_genes_map[key] = ",".join(genes)
        elif genes == "same as 16p11del":
            region_genes_map[key] = ",".join(dup_genes)
        else:
            region_genes_map[key] = ""
    return region_genes_map


def process_supp3(normalizer: GeneSymbolNormalizer) -> None:
    region_genes_map = build_region_genes_map()

    all_sheets = pd.read_excel(
        SUPP3_EXCEL, sheet_name=None, engine="openpyxl", dtype=str
    )
    print(f"Supp Table 3: read {len(all_sheets)} sheets")

    frames = []
    for sheet_name, df in all_sheets.items():
        deletion_type = get_deletion_type(sheet_name)

        # Rows without an HGNC symbol (e.g. non-coding RNAs) are dropped.
        # Row count drops from 808,380 to 720,945.
        df = df.dropna(subset=["hgnc_symbol"])
        df = df[df["hgnc_symbol"].astype(str).str.strip() != ""]

        df, _ = clean_gene_column(
            cast(pd.DataFrame, df),
            "hgnc_symbol",
            species="human",
            normalizer=normalizer,
            excel_demangle=True,
            strip_make_unique=True,
            manual_aliases=MANUAL_ALIASES,
        )
        df = df.drop(columns=["_hgnc_symbol_resolution"])

        df = df.rename(
            columns={  # type: ignore
                "hgnc_symbol": "target_gene",
                "hgnc_symbol_raw": "target_gene_raw",
                "ensembl_gene_id": "Ensembl_Gene_Id",
                "AveExpr": "Avg_Expr",
                "p": "P-Value",
                "fdr": "Adjusted_P-Value",
                "z.std": "z_std",
            }
        )

        df = df[
            [
                "target_gene",
                "target_gene_raw",
                "Ensembl_Gene_Id",
                "logFC",
                "Avg_Expr",
                "t",
                "P-Value",
                "Adjusted_P-Value",
                "z_std",
                "chromosome_name",
                "band",
                "gene_biotype",
            ]
        ]

        df.insert(0, "perturbation", deletion_type)
        df.insert(1, "organoid_age_(days)", get_organoid_age(sheet_name))
        df["region_genes"] = region_genes_map.get(deletion_type, "")

        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(SUPP3_OUT, sep="\t", index=False)
    print(f"Wrote {len(combined)} rows to {SUPP3_OUT}")


def process_supp12(normalizer: GeneSymbolNormalizer) -> None:
    all_sheets = pd.read_excel(
        SUPP12_EXCEL, sheet_name=None, engine="openpyxl", dtype=str
    )
    print(f"Supp Table 12: read {len(all_sheets)} sheets")

    frames = []
    for sheet_name, df in all_sheets.items():
        df = df.drop(columns=["...1"], errors="ignore")

        df = df.rename(
            columns={
                "gene": "target_gene",
                "avg_logFC": "Avg_logFC",
                "1.target.pct": "target_pct",
                "2.NTC.pct": "NTC_pct",
                "1.target.exp": "target_exp",
                "2.NTC.exp": "NTC_exp",
                "p_val": "P_Value",
                "p_val_adj": "Adjusted_P_Value",
            }
        )

        df, _ = clean_gene_column(
            df,
            "target_gene",
            species="human",
            normalizer=normalizer,
            excel_demangle=True,
            strip_make_unique=True,
            manual_aliases=MANUAL_ALIASES,
        )
        df = df.drop(columns=["_target_gene_resolution"])

        df.insert(0, "perturbed_gene", sheet_name)

        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(SUPP12_OUT, sep="\t", index=False)
    print(f"Wrote {len(combined)} rows to {SUPP12_OUT}")


def main() -> None:
    normalizer = GeneSymbolNormalizer.from_env()
    process_supp3(normalizer)
    process_supp12(normalizer)


if __name__ == "__main__":
    main()
