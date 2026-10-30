"""Preprocess Zheng et al. 2024 4TF Perturb-seq DEG data.

Cleans Excel-mangled gene names (e.g. `3-Mar`, `9-Sep`) in the Gene
column of `deg.txt` and splits the `perturbation` / `guide` compound
identifiers (e.g. `Foxg1_3`) into a parsed gene name + replicate index.
The split used to live at load-db time as `split_column_map:`; that
knob is being retired in favor of explicit preprocessing.

Writes a sibling `preprocessing.yaml` that records every action for
downstream provenance (#150).

Usage:
    python preprocess.py

Run inside the `processing` venv so that `from processing.preprocessing
import ...` resolves.

Inputs:
    deg.txt
    clusterprop.txt

Outputs (config.yaml reads these):
    deg_cleaned.txt
    clusterprop_cleaned.txt
    preprocessing.yaml   (provenance log)
"""

from pathlib import Path

from processing.preprocessing import (
    GeneSymbolNormalizer,
    Pipeline,
    Tracker,
)

DIR = Path(__file__).resolve().parent

# Table S4 only gives Seurat cluster numbers. The names are the row labels of
# Fig. 4F, which lists these 15 clusters in numeric order. Each match was checked
# against the significant guides in that figure, the cell type composition sheet
# of Table S4, and the fold changes quoted in the text (L6-IT cluster_5,
# L6-CT-c3 cluster_7, upper layer cluster_4).
#
# cluster_21 is drawn as "Inhib Id2", but the numbers disagree: Table S4 has 94
# Id2 cells, below the paper's 200-cell cutoff, while cluster_21 tracks the
# L5-IT cells not in cluster_6 across guides (r = 0.97). Keep the published
# label, marked, until the authors confirm it.
CELL_TYPE_BY_CLUSTER = {
    "cluster_0": "Excit L6CT-c1",
    "cluster_1": "Cajal Retzius-c1",
    "cluster_2": "Excit L6CT-c2",
    "cluster_3": "Excit L5NP",
    "cluster_4": "Excit Upper",
    "cluster_5": "Excit L6IT",
    "cluster_6": "Excit L5IT-c1",
    "cluster_7": "Excit L6CT-c3",
    "cluster_8": "Inhib Sst",
    "cluster_9": "Excit L2IT ENTl",
    "cluster_10": "Excit L5PT",
    "cluster_11": "Inhib Lhx6+Sst-",
    "cluster_12": "Excit L6b",
    "cluster_17": "Excit L6b/CT ENTl",
    "cluster_21": "Inhib Id2 (label unconfirmed)",
}


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    (
        Pipeline("deg_cleaned.txt", tracker=tracker, normalizer=normalizer)
        .read_tsv(DIR / "deg.txt")
        .clean_gene("Gene", species="mouse")
        # perturbation = "<gene>_<replicate>" (e.g. "Foxg1_3"). Surface the
        # parsed gene as its own visible column so users can search/click
        # it as a perturbed gene; replicate index stays for filtering.
        .split_column(
            "perturbation",
            "perturbation_gene",
            "perturbation_gene_idx",
            sep="_",
        )
        .reorder(
            [
                "perturbation_gene",
                "Gene",
                "PValue",
                "padj",
                "logFC",
                "logCPM",
                "LR",
                "cell type",
                "perturbation",
                "perturbation_gene_idx",
                "Gene_raw",
                "_Gene_resolution",
            ]
        )
        .write_tsv(DIR / "deg_cleaned.txt")
        .run()
    )

    (
        Pipeline("clusterprop_cleaned.txt", tracker=tracker, normalizer=normalizer)
        .read_tsv(DIR / "clusterprop.txt")
        # guide = "<gene>_<replicate>" (e.g. "Foxg1_1"). Same split logic
        # as the deg table.
        .split_column(
            "guide",
            "guide_gene",
            "guide_gene_idx",
            sep="_",
        )
        .insert_column(
            "cell_type",
            lambda df: df["subcluster"].map(CELL_TYPE_BY_CLUSTER),
        )
        .reorder(
            [
                "guide_gene",
                "cell_type",
                "subcluster",
                "P.Value",
                "FDR",
                "limma_coef",
                "Tstatistic",
                "PropRatio",
                "PropMean.treatGuide",
                "PropMean.treatNonTarget2",
                "guide",
                "guide_gene_idx",
            ]
        )
        .write_tsv(DIR / "clusterprop_cleaned.txt")
        .run()
    )


if __name__ == "__main__":
    main()
