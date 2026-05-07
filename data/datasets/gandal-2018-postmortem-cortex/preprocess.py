"""Preprocess Gandal et al. 2018 Science Supplementary Table S1 sheet "DGE".

Reads the per-gene differential gene-expression summary statistics
sheet from the supplementary tables xlsx (`aat8127_table_s1.xlsx`,
sheet `DGE`) and writes a clean per-gene TSV with columns renamed to
snake_case so the SSPsyGene loader's pvalue/fdr column-list wiring is
straightforward.

Source: 25,775 genes × bulk-cortex DE statistics for three NDDs (ASD,
schizophrenia, bipolar disorder) vs. controls (limma-voom on
PsychENCODE postmortem cortex bulk RNA-seq, Gandal et al. Science
2018).

Other sheets in the bundle (DTE / DTU / TWAS / WGCNA modules etc.)
are not ingested here — see makeDoc.txt for the per-sheet reasoning.

Issue: https://github.com/sspsygene-dracc/psypheno/issues/56

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing import …`
resolves.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, Pipeline, Tracker

DIR = Path(__file__).resolve().parent
RAW_FILE = DIR / "aat8127_table_s1.xlsx"
OUT_FILE = DIR / "gandal_2018_bulk_de.tsv"

# Snake-case rename for the disease × statistic columns so
# pvalue_column / fdr_column lists in config.yaml are clean.
RENAMES = {
    "gene_name": "gene_symbol",
    "ASD.log2FC": "asd_log2fc",
    "ASD.Std.Error": "asd_std_error",
    "ASD.DF": "asd_df",
    "ASD.t.value": "asd_t_value",
    "ASD.p.value": "asd_p_value",
    "ASD.fdr": "asd_fdr",
    "SCZ.log2FC": "scz_log2fc",
    "SCZ.Std.Error": "scz_std_error",
    "SCZ.DF": "scz_df",
    "SCZ.t.value": "scz_t_value",
    "SCZ.p.value": "scz_p_value",
    "SCZ.fdr": "scz_fdr",
    "BD.log2FC": "bd_log2fc",
    "BD.Std.Error": "bd_std_error",
    "BD.DF": "bd_df",
    "BD.t.value": "bd_t_value",
    "BD.p.value": "bd_p_value",
    "BD.fdr": "bd_fdr",
}


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    df = pd.read_excel(RAW_FILE, sheet_name="DGE")

    (
        Pipeline(OUT_FILE.name, tracker=tracker, normalizer=normalizer)
        .from_dataframe(df, label="TableS1_DGE")
        .rename(RENAMES)
        .clean_gene("gene_symbol", species="human", resolve_via_ensembl_map=False)
        .write_tsv(OUT_FILE)
        .run()
    )


if __name__ == "__main__":
    main()
