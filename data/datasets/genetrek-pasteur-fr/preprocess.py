"""Preprocess the GeneTrek per-gene NDD/autism annotation TSV.

Reads the genetrek TSV (manually downloaded from
https://genetrek.pasteur.fr/) and produces a clean, gene-centric TSV
suitable for the SSPsyGene loader. Concretely:

* drops the six hg19/hg38 coordinate columns — SSPsyGene is gene-centric,
  not coordinate-based;
* renames a few key columns to clean snake_case so the
  pvalue_column / effect_column wiring in config.yaml is straightforward
  (pandas' col-name sanitizer handles the messier ones);
* runs `Gene` through the standard clean_gene step so HGNC resolution
  happens at preprocess time (raw value preserved in `Gene_raw`).

Issue: https://github.com/sspsygene-dracc/psypheno/issues/11

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing import …`
resolves.
"""

from __future__ import annotations

from pathlib import Path

from processing.preprocessing import GeneSymbolNormalizer, Pipeline, Tracker

DIR = Path(__file__).resolve().parent
RAW_FILE = DIR / "genetrek-data-2024-04-26.tsv"
OUT_FILE = DIR / "genetrek_pasteur_cleaned.tsv"

COORD_COLS = [
    "hg19 - start",
    "hg19 - end",
    "hg19 - chromosome",
    "hg38 - start",
    "hg38 - end",
    "hg38 - chromosome",
]

RENAMES = {
    "Gene": "gene_symbol",
    "Autism odds ratio": "autism_or",
    "p-value": "autism_or_pvalue",
    "Confidence interval lower bound": "autism_or_ci_lower",
    "Confidence interval upper bound": "autism_or_ci_upper",
    "Prevalence autism": "prevalence_autism",
    "Prevalence controls": "prevalence_controls",
    "Number of carriers among autistic individuals": "n_carriers_autism",
}


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    (
        Pipeline(OUT_FILE.name, tracker=tracker, normalizer=normalizer)
        .read_tsv(RAW_FILE)
        .drop_columns(COORD_COLS, errors="ignore")
        .rename(RENAMES)
        .clean_gene("gene_symbol", species="human", resolve_via_ensembl_map=False)
        .write_tsv(OUT_FILE)
        .run()
    )


if __name__ == "__main__":
    main()
