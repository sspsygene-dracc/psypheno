"""Preprocess Deans et al. 2026 polygenic-risk-20 supplementary tables.

Cleans both gene-name columns in Supp_1_all.csv and Supp_2_all.csv:

  * Tier A (excel_demangle): ISO-date forms `2023-03-01` ... `2023-03-11`
    -> MARCHF*; `2023-09-01` ... `2023-09-12` -> SEPTIN*. Both files
    contain these in `target_gene`; #143's scope listed Supp_1 only,
    but Supp_2 has the same ISO-date set so the flag is enabled there
    too.
  * Tier C2 (strip_make_unique): R `make.unique` `.N` suffixes such as
    `MATR3.1`, `TBCE.1`. The helper rescues these only when the
    un-suffixed form resolves and the suffixed form does not, so
    GenBank composites like `KC877982.1` correctly pass through to
    Tier B's silencer.
  * Tier C4 (resolve_gencode_clone): legacy GENCODE/HAVANA clone
    identifiers (`RP11-…`, `CTD-…`, `KB-…`, `XXbac-…`, …). Roughly
    5,100 unique clone-shaped target_gene values in Supp_1 alone; the
    GENCODE v38 + HGNC cross-reference resolves ~66% of them to the
    current HGNC symbol, the stable ENSG anchor, or a current AC
    accession. The remainder fall through to the existing Tier B
    `gencode_clone` silencer (#139).

`perturbed_gene` columns hold a small set of canonical CRISPR-target
symbols (no mangling today) but are routed through the cleaner for
symmetry.

Writes a sibling `preprocessing.yaml` (#150) with per-file action records.

Usage:
    python preprocess.py

Run inside the `processing` venv so `from processing.preprocessing
import ...` resolves.
"""

from pathlib import Path

from processing.preprocessing import (
    GeneSymbolNormalizer,
    MANUAL_ALIASES_HUMAN,
    Pipeline,
    Tracker,
)

DIR = Path(__file__).resolve().parent

JOBS: list[tuple[str, str]] = [
    ("Supp_1_all.csv", "Supp_1_all_cleaned.csv"),
    ("Supp_2_all.csv", "Supp_2_all_cleaned.csv"),
]
GENE_COLUMNS = ("perturbed_gene", "target_gene")


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    for in_name, out_name in JOBS:
        pipe = (
            Pipeline(out_name, tracker=tracker, normalizer=normalizer)
            .read_csv(DIR / in_name)
        )
        for column in GENE_COLUMNS:
            pipe = pipe.clean_gene(
                column,
                species="human",
                manual_aliases=MANUAL_ALIASES_HUMAN,
            )
        pipe.write_csv(DIR / out_name).run()

    tracker.write(DIR / "preprocessing.yaml")


if __name__ == "__main__":
    main()
