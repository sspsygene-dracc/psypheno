"""Shared preprocessing utilities for dataset wranglers.

Per-dataset preprocess.py scripts in `data/datasets/*/` import from
this module to clean gene-name columns and record the changes they
make. Goals: keep `load-db` strict and small, give wranglers a
discoverable library to compose pipelines from, and make every manual
change visible to downstream users via a per-dataset
`preprocessing.yaml` provenance file.

Two layers:

1. **Free-function gene-cleanup** — `clean_gene_column` plus tier-aware
   helpers (`excel_demangle`, `strip_make_unique_suffix`, …). Stable;
   used by all the existing scripts.

2. **Pipeline + Tracker** — composable `Pipeline` of `Step`s that
   threads a `Tracker` through every operation. Records each action so
   the resulting `preprocessing.yaml` describes exactly what was done.

Example (pipeline form):

    from pathlib import Path
    from processing.preprocessing import (
        GeneSymbolNormalizer, Pipeline, Tracker, MANUAL_ALIASES_HUMAN,
    )

    DIR = Path(__file__).resolve().parent
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    (
        Pipeline("cleaned.csv", tracker=tracker, normalizer=normalizer)
        .read_csv(DIR / "raw.csv")
        .clean_gene("target_gene", species="human",
                    excel_demangle=True, manual_aliases=MANUAL_ALIASES_HUMAN)
        .write_csv(DIR / "cleaned.csv")
        .run()
    )
    tracker.write(DIR / "preprocessing.yaml")
"""

from processing.preprocessing.dataframe import CleanReport, clean_gene_column
from processing.preprocessing.ensembl_index import EnsemblToSymbolMapper
from processing.preprocessing.helpers import (
    NON_SYMBOL_CATEGORIES,
    NonSymbolCategory,
    excel_demangle,
    is_non_symbol_identifier,
    split_symbol_ensg,
    strip_make_unique_suffix,
)
from processing.preprocessing.pipeline import (
    MANUAL_ALIASES_HUMAN,
    ActionRecord,
    Context,
    Pipeline,
    Tracker,
    copy_file,
)
from processing.preprocessing.steps import (
    CleanGeneColumnStep,
    DropColumns,
    DropNa,
    FilterRows,
    InsertColumn,
    ReadCsv,
    Rename,
    Reorder,
    Step,
    TransformColumn,
    WriteCsv,
)
from processing.preprocessing.symbol_index import GeneSymbolNormalizer, Species

__all__ = [
    # Gene-cleanup core
    "CleanReport",
    "EnsemblToSymbolMapper",
    "GeneSymbolNormalizer",
    "NON_SYMBOL_CATEGORIES",
    "NonSymbolCategory",
    "Species",
    "clean_gene_column",
    "excel_demangle",
    "is_non_symbol_identifier",
    "split_symbol_ensg",
    "strip_make_unique_suffix",
    # Pipeline / tracker
    "ActionRecord",
    "Context",
    "MANUAL_ALIASES_HUMAN",
    "Pipeline",
    "Tracker",
    "copy_file",
    # Built-in step types
    "CleanGeneColumnStep",
    "DropColumns",
    "DropNa",
    "FilterRows",
    "InsertColumn",
    "ReadCsv",
    "Rename",
    "Reorder",
    "Step",
    "TransformColumn",
    "WriteCsv",
]
