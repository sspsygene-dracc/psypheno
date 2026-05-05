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
        .reorder(
            [
                "guide_gene",
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
