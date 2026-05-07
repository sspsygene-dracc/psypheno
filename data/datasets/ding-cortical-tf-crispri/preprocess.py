"""Preprocess Ding et al. 2026 supplementary tables for SSPsyGene.

Reads the multi-sheet Supplementary Information workbook
(`41586_2025_9997_MOESM1_ESM.xlsx`, downloaded manually — see
makeDoc.txt) and writes two cleaned TSVs:

* `ding_2026_deg_human.tsv` — Table S5, the per-gene DEG list across
  all 40 TFs and 7 cell types tested in the human cortical-RG CRISPRi
  screen. Columns: genes, baseMean, log2FoldChange, lfcSE, stat,
  pvalue, padj, Target.Gene, Cell.Type. Both `genes` (target measured)
  and `Target.Gene` (perturbed TF) get HGNC-resolved at preprocess
  time.

* `ding_2026_deg_arx_in_lmo1ric3.tsv` — Table S8, DEGs in the
  IN_LMO1/RIC3 ectopic cluster induced by ARX KD. Same DESeq2 stats,
  but no Target.Gene/Cell.Type columns in the source — Target.Gene is
  inserted as a constant 'ARX' (per the sheet title) so the
  perturbed-gene mapping wires up correctly in config.yaml.

Tables S1 / S2 / S3 / S4 / S6 / S7 are skipped — see makeDoc.txt for
the per-sheet reasoning.

Issue: https://github.com/sspsygene-dracc/psypheno/issues/22

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
RAW_FILE = DIR / "41586_2025_9997_MOESM1_ESM.xlsx"
OUT_HUMAN = DIR / "ding_2026_deg_human.tsv"
OUT_ARX = DIR / "ding_2026_deg_arx_in_lmo1ric3.tsv"


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    # Sheet header is on row 1 (0-indexed) — row 0 is a free-text
    # "Supplementary Table N. …" caption.
    s5 = pd.read_excel(RAW_FILE, sheet_name="TableS5. DEG-human", skiprows=1)
    s8 = pd.read_excel(RAW_FILE, sheet_name="TableS8. DEG-IN_LMO1RIC3", skiprows=1)

    (
        Pipeline(OUT_HUMAN.name, tracker=tracker, normalizer=normalizer)
        .from_dataframe(s5, label="TableS5_DEG-human")
        .clean_gene("genes", species="human", resolve_via_ensembl_map=False)
        .clean_gene("Target.Gene", species="human", resolve_via_ensembl_map=False)
        .write_tsv(OUT_HUMAN)
        .run()
    )

    (
        Pipeline(OUT_ARX.name, tracker=tracker, normalizer=normalizer)
        .from_dataframe(s8, label="TableS8_DEG-IN_LMO1RIC3")
        .insert_column("Target.Gene", "ARX")
        .clean_gene("genes", species="human", resolve_via_ensembl_map=False)
        .clean_gene("Target.Gene", species="human", resolve_via_ensembl_map=False)
        .write_tsv(OUT_ARX)
        .run()
    )


if __name__ == "__main__":
    main()
