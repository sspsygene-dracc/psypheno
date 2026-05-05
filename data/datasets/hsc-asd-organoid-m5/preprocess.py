"""Preprocess Gordon et al. 2026 ASD organoid DE results.

Reads Supplementary Table 3 (45 sheets, one per perturbation x
timepoint) and Supplementary Table 12 (26 sheets, one per M5
transcription factor) from the downloaded Excel files and produces two
TSVs.

Both reads pass `dtype=str` so any Excel-mangled date cells (e.g.
`1-Mar`, `9-Sep`) survive as strings rather than being silently
converted to Timestamps. Each sheet's gene column flows through a
per-sheet `Pipeline` that calls `clean_gene` — Pipeline's defaults
turn on every shape-gated resolver (excel_demangle,
strip_make_unique, resolve_hgnc_id, resolve_via_ensembl_map,
resolve_gencode_clone, split_symbol_ensg) so the script only needs
to specify the per-dataset `manual_aliases`. Numeric columns become
strings on the way through and re-parse to numerics when the TSV is
loaded downstream.

The per-sheet pipelines all share one `Tracker`, so the resulting
`preprocessing.yaml` (#150) records every action across all 45+26
sheets, keyed by sheet name.

Usage:
    python preprocess.py

Input files (place in this directory):
    Supp_table_3_-_DE_results.xlsx
    Supp_table_12_-_DE_targets_of_M5_TFs.xlsx

Output files:
    supplementary_table_3_DE_results.tsv
    supplementary_table_12_DE_targets_M5_TFs.tsv
    preprocessing.yaml   (provenance log)
"""

import json
from pathlib import Path

import pandas as pd

from processing.preprocessing import (
    GeneSymbolNormalizer,
    Pipeline,
    Tracker,
)

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


def _non_empty_hgnc(d: pd.DataFrame) -> pd.Series:
    return d["hgnc_symbol"].astype(str).str.strip() != ""


def process_supp3(
    tracker: Tracker,
    normalizer: GeneSymbolNormalizer,
) -> None:
    region_genes_map = build_region_genes_map()

    all_sheets = pd.read_excel(
        SUPP3_EXCEL, sheet_name=None, engine="openpyxl", dtype=str
    )
    print(f"Supp Table 3: read {len(all_sheets)} sheets")
    tracker.note_input(SUPP3_EXCEL.name)

    frames: list[pd.DataFrame] = []
    for sheet_name, sheet_df in all_sheets.items():
        deletion_type = get_deletion_type(sheet_name)

        cleaned = (
            Pipeline(
                f"supp3:{sheet_name}",
                tracker=tracker,
                normalizer=normalizer,
            )
            .from_dataframe(sheet_df, label=f"sheet={sheet_name}")
            # Rows without an HGNC symbol (e.g. non-coding RNAs) are dropped.
            # Row count drops from 808,380 to 720,945 across all 45 sheets.
            .dropna(["hgnc_symbol"])
            .filter_rows(_non_empty_hgnc, description="non-empty hgnc_symbol")
            .clean_gene(
                "hgnc_symbol",
                species="human",
                manual_aliases=MANUAL_ALIASES,
            )
            .rename(
                {
                    "hgnc_symbol": "target_gene",
                    "hgnc_symbol_raw": "target_gene_raw",
                    "ensembl_gene_id": "Ensembl_Gene_Id",
                    "AveExpr": "Avg_Expr",
                    "p": "P-Value",
                    "fdr": "Adjusted_P-Value",
                    "z.std": "z_std",
                }
            )
            .reorder(
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
            )
            .insert_column("perturbation", deletion_type, position=0)
            .insert_column(
                "organoid_age_(days)", get_organoid_age(sheet_name), position=1
            )
            .insert_column(
                "region_genes", region_genes_map.get(deletion_type, "")
            )
            .run()
        )
        frames.append(cleaned)

    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(SUPP3_OUT, sep="\t", index=False)
    tracker.write_concat(
        SUPP3_OUT,
        inputs=[SUPP3_EXCEL.name],
        sheets=len(frames),
        rows=len(combined),
    )
    print(f"Wrote {len(combined)} rows to {SUPP3_OUT}")


def process_supp12(
    tracker: Tracker,
    normalizer: GeneSymbolNormalizer,
) -> None:
    all_sheets = pd.read_excel(
        SUPP12_EXCEL, sheet_name=None, engine="openpyxl", dtype=str
    )
    print(f"Supp Table 12: read {len(all_sheets)} sheets")
    tracker.note_input(SUPP12_EXCEL.name)

    frames: list[pd.DataFrame] = []
    for sheet_name, sheet_df in all_sheets.items():
        cleaned = (
            Pipeline(
                f"supp12:{sheet_name}",
                tracker=tracker,
                normalizer=normalizer,
            )
            .from_dataframe(sheet_df, label=f"sheet={sheet_name}")
            .drop_columns(["...1"], errors="ignore")
            .rename(
                {
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
            .clean_gene(
                "target_gene",
                species="human",
                manual_aliases=MANUAL_ALIASES,
            )
            .insert_column("perturbed_gene", sheet_name, position=0)
            .run()
        )
        frames.append(cleaned)

    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(SUPP12_OUT, sep="\t", index=False)
    tracker.write_concat(
        SUPP12_OUT,
        inputs=[SUPP12_EXCEL.name],
        sheets=len(frames),
        rows=len(combined),
    )
    print(f"Wrote {len(combined)} rows to {SUPP12_OUT}")


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()
    process_supp3(tracker, normalizer)
    process_supp12(tracker, normalizer)


if __name__ == "__main__":
    main()
