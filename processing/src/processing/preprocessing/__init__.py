"""Shared preprocessing utilities for dataset wranglers.

Per-dataset preprocess.py scripts in `data/datasets/*/` import from
this module to clean gene-name columns before the data reaches
`load-db`. The goal: keep `load-db` strict and small, and have one
place to grow whenever a new dataset surfaces a new edge case.

Example:

    from processing.preprocessing import (
        GeneSymbolNormalizer,
        clean_gene_column,
    )

    normalizer = GeneSymbolNormalizer.from_env()
    df, report = clean_gene_column(
        df, "target_gene", species="human", normalizer=normalizer,
        excel_demangle=True, strip_make_unique=True,
    )
"""

from processing.preprocessing.dataframe import CleanReport, clean_gene_column
from processing.preprocessing.helpers import (
    NonSymbolCategory,
    excel_demangle,
    is_non_symbol_identifier,
    split_symbol_ensg,
    strip_make_unique_suffix,
)
from processing.preprocessing.symbol_index import GeneSymbolNormalizer, Species

__all__ = [
    "CleanReport",
    "GeneSymbolNormalizer",
    "NonSymbolCategory",
    "Species",
    "clean_gene_column",
    "excel_demangle",
    "is_non_symbol_identifier",
    "split_symbol_ensg",
    "strip_make_unique_suffix",
]
