"""Preprocess Velmeshev et al. 2019 Science Supplementary Table S4.

Reads the 'ASD_DEGs' sheet from the XLS supplement and writes a clean
per-gene per-cell-type TSV of ASD-vs-control differential expression
results from postmortem cortex single-nucleus RNA-seq.

Key facts about the source table:
- 692 rows, 17 cell types, 513 unique genes
- Fold change is log2 (despite the column name 'Fold change'); the
  paper's stated cutoff of 0.14 maps to log2(1.10) ≈ 0.137, confirming
  the scale (Supplementary Methods, section "Differential expression
  analysis").
- Only a q-value (FDR) is provided; no raw p-value.
- Gene ID column contains Ensembl IDs; Gene name column contains HGNC
  symbols. We surface the HGNC symbol as the primary gene column and
  keep the Ensembl ID as gene_id.

Issue: https://github.com/sspsygene-dracc/psypheno/issues/198

Usage:
    python preprocess.py

Run inside the sspsygene conda env so `from processing.preprocessing
import ...` resolves.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, Pipeline, Tracker

DIR = Path(__file__).resolve().parent
RAW_FILE = DIR / "supplementary-table4.xls"
OUT_FILE = DIR / "velmeshev_2019_degs.tsv"

RENAMES = {
    "Cell type": "cell_type",
    "gene ID": "gene_id",
    "Gene name": "gene",
    "Gene biotype": "gene_biotype",
    "Fold change": "fold_change",
    "Sample fold change": "sample_fold_change",
    "q value": "q_value",
    "correlation (bulk mRNA/bulkized nuclear RNA)": "bulk_correlation",
    "Epilepsy DEG": "epilepsy_deg",
    "gene group": "gene_group",
    "SFARI gene": "sfari_gene",
    "Satterstrom": "satterstrom",
    "Sanders": "sanders",
    "cell type-specific expression": "cell_type_specific",
}


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    raw = pd.read_excel(RAW_FILE, sheet_name="ASD_DEGs", header=0)
    raw = raw.rename(columns=RENAMES)

    (
        Pipeline(OUT_FILE.name, tracker=tracker, normalizer=normalizer)
        .from_dataframe(raw, label="TableS4_ASD_DEGs")
        .clean_gene(
            "gene",
            species="human",
            excel_demangle=True,
            strip_make_unique=True,
        )
        .write_tsv(OUT_FILE)
        .run()
    )


if __name__ == "__main__":
    main()
