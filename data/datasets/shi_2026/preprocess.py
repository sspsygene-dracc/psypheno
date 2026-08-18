"""Preprocess Shi et al. 2026 whole-brain in vivo Perturb-seq DEG data.

Reads two parquet files provided by the authors:
  - wilcoxon_de_results.parquet: full Wilcoxon DEG results (745M rows);
    filtered here to pvals_adj < 0.05.
  - DESEQ2_group_name_ALL_targets_vs_Non_target_with_expr_dropout_edit_FDR_0.05.parquet:
    DESeq2 pseudobulk DEG results, already filtered to FDR < 0.05 by authors.

Both files contain per-(perturbation, cell-type, gene) DEG statistics from
in vivo Perturb-seq of 1,947 disease-associated genes across the mouse
whole brain.

Usage:
    python preprocess.py

Outputs:
    shi_2026_wilcoxon.tsv
    shi_2026_deseq2.tsv
"""

from pathlib import Path

import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, Pipeline, Tracker

DIR = Path(__file__).resolve().parent

WILCOXON_FILE = DIR / "wilcoxon_de_results.parquet"
DESEQ2_FILE = DIR / (
    "DESEQ2_group_name_ALL_targets_vs_Non_target_with_expr_dropout_edit_FDR_0.05.parquet"
)

FDR_THRESHOLD = 0.05

_PROVENANCE_COLS = [
    "gene_raw", "_gene_resolution",
    "perturbation_raw", "_perturbation_resolution",
]

# Space-separated token expansions — only exact whole tokens are replaced,
# so abbreviations inside hyphenated compounds (e.g. CTX in CTX-CGE) are left as-is.
_ABBREVS = {
    "IT": "Intratelencephalic",
    "ET": "Extratelencephalic",
    "Glut": "Glutamatergic",
    "GABA": "GABAergic",
    "Gaba": "GABAergic",
    "Dopa": "Dopaminergic",
    "Pvalb": "Parvalbumin",
    "Sst": "Somatostatin",
    "CTX": "Cortex",
    "HY": "Hypothalamus",
    "MB": "Midbrain",
    "TH": "Thalamus",
    "CB": "Cerebellum",
    "MY": "Medulla",
    "P": "Pons",
}


def _clean_cell_type(series):
    """Strip numeric cluster prefix and expand standard abbreviations in cell type labels."""
    result = series.str.replace(r"^\d+\s+", "", regex=True)
    return result.apply(
        lambda s: " ".join(_ABBREVS.get(t, t) for t in s.split(" "))
    )


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    # ── Wilcoxon DEGs ────────────────────────────────────────────────────────
    wilcoxon_df = pd.read_parquet(
        WILCOXON_FILE,
        filters=[("pvals_adj", "<", FDR_THRESHOLD)],
        columns=[
            "names", "scores", "logfoldchanges", "pvals", "pvals_adj",
            "group_name", "gene_target", "n_pert_matched", "n_ctrl_matched",
        ],
    ).rename(columns={
        "names": "gene",
        "scores": "z_score",
        "logfoldchanges": "log2fc",
        "pvals": "pval",
        "pvals_adj": "pval_adj",
        "group_name": "cell_type",
        "gene_target": "perturbation",
        "n_pert_matched": "n_cells_perturbed",
        "n_ctrl_matched": "n_cells_control",
    })
    wilcoxon_df["n_cells_perturbed"] = wilcoxon_df["n_cells_perturbed"].astype(int)
    wilcoxon_df["n_cells_control"] = wilcoxon_df["n_cells_control"].astype(int)

    (
        Pipeline("shi_2026_wilcoxon.tsv", tracker=tracker, normalizer=normalizer)
        .from_dataframe(wilcoxon_df)
        .filter_rows(
            lambda df: ~df["perturbation"].str.startswith("Safe_target", na=False),
            description="Remove safe-harbor CRISPR control rows (Safe_target_*)",
        )
        .clean_gene("gene", species="mouse")
        .clean_gene("perturbation", species="mouse")
        .transform_column(
            "cell_type", _clean_cell_type,
            description="Strip numeric cluster prefix and expand cell type abbreviations",
        )
        .drop_columns(_PROVENANCE_COLS)
        .reorder([
            "perturbation", "gene", "cell_type",
            "log2fc", "z_score", "pval", "pval_adj",
            "n_cells_perturbed", "n_cells_control",
        ])
        .write_tsv(DIR / "shi_2026_wilcoxon.tsv")
        .run()
    )

    # ── DESeq2 DEGs ──────────────────────────────────────────────────────────
    deseq2_df = pd.read_parquet(
        DESEQ2_FILE,
        columns=[
            "gene", "log2FoldChange", "lfcSE", "stat", "pvalue", "padj",
            "baseMean", "target", "group_name", "n_cells_target",
            "n_cells_reference", "dropout_rate_perturb",
            "mean_expr_perturb", "mean_expr_control",
        ],
    ).rename(columns={
        "log2FoldChange": "log2fc",
        "lfcSE": "lfcse",
        "pvalue": "pval",
        "padj": "pval_adj",
        "baseMean": "basemean",
        "target": "perturbation",
        "group_name": "cell_type",
        "n_cells_target": "n_cells_perturbed",
        "n_cells_reference": "n_cells_control",
    })
    deseq2_df["n_cells_perturbed"] = deseq2_df["n_cells_perturbed"].astype(int)
    deseq2_df["n_cells_control"] = deseq2_df["n_cells_control"].astype(int)

    (
        Pipeline("shi_2026_deseq2.tsv", tracker=tracker, normalizer=normalizer)
        .from_dataframe(deseq2_df)
        .filter_rows(
            lambda df: ~df["perturbation"].str.startswith("Safe_target", na=False),
            description="Remove safe-harbor CRISPR control rows (Safe_target_*)",
        )
        .clean_gene("gene", species="mouse")
        .clean_gene("perturbation", species="mouse")
        .transform_column(
            "cell_type", _clean_cell_type,
            description="Strip numeric cluster prefix and expand cell type abbreviations",
        )
        .drop_columns(_PROVENANCE_COLS)
        .reorder([
            "perturbation", "gene", "cell_type",
            "log2fc", "lfcse", "stat", "pval", "pval_adj",
            "basemean", "n_cells_perturbed", "n_cells_control",
            "dropout_rate_perturb", "mean_expr_perturb", "mean_expr_control",
        ])
        .write_tsv(DIR / "shi_2026_deseq2.tsv")
        .run()
    )


if __name__ == "__main__":
    main()
