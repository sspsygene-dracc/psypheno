"""Preprocess Gandal et al. 2022 Nature supplementary data.

Reads two sheets from the Nature Supplementary Information bundle and
writes per-gene cleaned TSVs:

* `gandal_2022_bulk_de_per_region.tsv` — Suppl. Data 3 (MOESM5) sheet
  `DEGene_Statistics`, 24,837 genes × 63 cols. Bulk-cortex limma DE
  for ASD and the dup15q subtype with whole-cortex averages and
  per-Brodmann-area breakdowns. Both `gene` (the measured gene)
  resolves to HGNC symbols via clean_gene.

* `gandal_2022_singlecell_de.tsv` — Suppl. Data 8 (MOESM10) sheet
  `DEA_ASDvCTL_sumstats`, 86,670 (cell-type × region × gene) rows of
  single-nucleus ASD-vs-CTL DE. Long format.

Other sheets — DEIsoform_Statistics (per-isoform), GeneModules /
IsoformModules (WGCNA), ARI / methylation analyses, etc. — are
intentionally skipped; see makeDoc.txt for the per-sheet reasoning.

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
RAW_BULK = DIR / "41586_2022_5377_MOESM5_ESM.xlsx"
RAW_SINGLECELL = DIR / "41586_2022_5377_MOESM10_ESM.xlsx"
OUT_BULK = DIR / "gandal_2022_bulk_de_per_region.tsv"
OUT_SC = DIR / "gandal_2022_singlecell_de.tsv"

# Bulk-DE sheet rename: keep the original `external_gene_name` as the
# canonical HGNC symbol column; rename to `gene_symbol` for clarity
# and consistency with the rest of the dataset.
RENAMES_BULK = {
    "external_gene_name": "gene_symbol",
}

# Single-cell sheet rename: the source uses `gene` / `cell` / `region`
# / `P-value` / `logFC` / `FDR-corrected P` headers. Snake-case the
# stat columns and rename `cell` → `cell_type` for clarity.
RENAMES_SC = {
    "cell": "cell_type",
    "P-value": "pvalue",
    "logFC": "log2fc",
    "FDR-corrected P": "fdr",
}


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    bulk = pd.read_excel(RAW_BULK, sheet_name="DEGene_Statistics")
    (
        Pipeline(OUT_BULK.name, tracker=tracker, normalizer=normalizer)
        .from_dataframe(bulk, label="MOESM5_DEGene_Statistics")
        .rename(RENAMES_BULK)
        .clean_gene("gene_symbol", species="human", resolve_via_ensembl_map=False)
        .write_tsv(OUT_BULK)
        .run()
    )

    # MOESM10's DEA_ASDvCTL_sumstats sheet has a "DE_ASDvsCTL_Nebula_Mixed_Model"
    # caption row above the actual header — skip it.
    sc = pd.read_excel(
        RAW_SINGLECELL,
        sheet_name="DEA_ASDvCTL_sumstats",
        skiprows=1,
    )
    (
        Pipeline(OUT_SC.name, tracker=tracker, normalizer=normalizer)
        .from_dataframe(sc, label="MOESM10_DEA_ASDvCTL_sumstats")
        .rename(RENAMES_SC)
        .clean_gene("gene", species="human", resolve_via_ensembl_map=False)
        .write_tsv(OUT_SC)
        .run()
    )


if __name__ == "__main__":
    main()
