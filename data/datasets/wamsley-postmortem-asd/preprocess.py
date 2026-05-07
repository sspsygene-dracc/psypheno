"""Preprocess Wamsley et al. 2024 Science supplementary table S1C.

Reads the cluster-marker sheet from the supplementary-tables xlsx
bundle (`science.adh2602_table_s1.xlsx`, sheet `(C)Cluster Marker
genes`) and writes a clean per-gene-per-cluster TSV. Each row is one
gene's marker statistics (Seurat FindMarkers output: pct.1 vs pct.2)
within one cell-type cluster from the 66-donor postmortem cortex
snRNA-seq taxonomy.

The xlsx puts the actual header on row 3 (rows 1-2 are the
free-text caption); we skip those.

Other sheets in the bundle (S1A/B/D, S2-S7) are not ingested here —
see makeDoc.txt for the per-sheet reasoning.

Issue: https://github.com/sspsygene-dracc/psypheno/issues/55

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
RAW_FILE = DIR / "science.adh2602_table_s1.xlsx"
OUT_FILE = DIR / "wamsley_2024_cluster_markers.tsv"


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    s1c = pd.read_excel(
        RAW_FILE,
        sheet_name="(C)Cluster Marker genes",
        skiprows=2,
    )
    # The sheet has a duplicate `gene2` column at the end — same content as
    # `gene`. Drop it; the `gene` column is canonical.
    s1c = s1c.drop(columns=["gene2"], errors="ignore")

    (
        Pipeline(OUT_FILE.name, tracker=tracker, normalizer=normalizer)
        .from_dataframe(s1c, label="TableS1C_ClusterMarkerGenes")
        .clean_gene("gene", species="human", resolve_via_ensembl_map=False)
        .write_tsv(OUT_FILE)
        .run()
    )


if __name__ == "__main__":
    main()
