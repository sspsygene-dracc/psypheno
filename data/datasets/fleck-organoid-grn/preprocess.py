"""Preprocess the Fleck et al. 2023 organoid GRN modules table.

Downloads grn_modules.tsv from
https://zenodo.org/records/5242913 (DOI 10.5281/zenodo.5242913) — the
Pando-inferred TF→target gene regulatory network from "Inferring and
perturbing cell fate regulomes in human brain organoids" (Fleck JS et al.,
Nature 2023, PMID 36198796) — and runs it through the standard preprocess
pipeline so the gene-symbol columns (`tf` and `target`) get HGNC-resolved
with raw values preserved in `<col>_raw`.

The Zenodo record also includes seurat_objects.tar.gz (~18 GB) and a
demuxed VCF; neither is ingested here. Only grn_modules.tsv is on the
SSPsyGene request path (per issue #13).

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing import …`
resolves.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from processing.preprocessing import GeneSymbolNormalizer, Pipeline, Tracker

DIR = Path(__file__).resolve().parent
SOURCE_URL = (
    "https://zenodo.org/api/records/5242913/files/grn_modules.tsv/content"
)
RAW_FILE = DIR / "grn_modules.tsv"
OUT_FILE = DIR / "fleck_organoid_grn_modules.tsv"


def download_if_missing(url: str, dest: Path) -> None:
    if dest.exists():
        return
    urllib.request.urlretrieve(url, dest)


def main() -> None:
    download_if_missing(SOURCE_URL, RAW_FILE)

    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    (
        Pipeline(OUT_FILE.name, tracker=tracker, normalizer=normalizer)
        .read_tsv(RAW_FILE)
        .clean_gene("tf", species="human", resolve_via_ensembl_map=False)
        .clean_gene("target", species="human", resolve_via_ensembl_map=False)
        .write_tsv(OUT_FILE)
        .run()
    )


if __name__ == "__main__":
    main()
