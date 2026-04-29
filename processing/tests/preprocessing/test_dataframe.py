import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, clean_gene_column


def test_clean_gene_column_full_pipeline(normalizer: GeneSymbolNormalizer) -> None:
    df = pd.DataFrame(
        {
            "target_gene": [
                "BRCA1",          # passed_through
                "DEC1",           # passed_through (alias → DELEC1)
                "9-Sep",          # rescued_excel
                "2023-09-04",     # rescued_excel
                "MATR3.1",        # rescued_make_unique
                "TBCE_ENSG00000284770",  # rescued_symbol_ensg
                "ENSG00000123456",  # non_symbol_ensembl_human
                "RP11-783K16.5",  # non_symbol_gencode_clone
                "WHO_KNOWS",      # unresolved
                "",               # passed_through (empty)
            ],
            "extra": list(range(10)),
        }
    )
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        excel_demangle=True,
        strip_make_unique=True,
        split_symbol_ensg=True,
    )

    assert out["target_gene"].tolist() == [
        "BRCA1",
        "DELEC1",
        "SEPTIN9",
        "SEPTIN4",
        "MATR3",
        "TBCE",
        "ENSG00000123456",
        "RP11-783K16.5",
        "WHO_KNOWS",
        "",
    ]
    assert report.resolutions == [
        "passed_through",
        "passed_through",
        "rescued_excel",
        "rescued_excel",
        "rescued_make_unique",
        "rescued_symbol_ensg",
        "non_symbol_ensembl_human",
        "non_symbol_gencode_clone",
        "unresolved",
        "passed_through",
    ]
    assert report.dropped_indices == []
    assert "extra" in out.columns
    assert "_target_gene_resolution" in out.columns


def test_clean_gene_column_drop_non_symbols(
    normalizer: GeneSymbolNormalizer,
) -> None:
    df = pd.DataFrame(
        {
            "target_gene": ["BRCA1", "ENSG00000123456", "MATR3"],
        }
    )
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        drop_non_symbols=True,
    )
    assert out["target_gene"].tolist() == ["BRCA1", "MATR3"]
    assert report.dropped_indices == [1]


def test_clean_gene_column_resolve_hgnc_id(
    normalizer: GeneSymbolNormalizer,
) -> None:
    df = pd.DataFrame(
        {
            "hgnc_symbol": [
                "BRCA1",         # passed_through
                "HGNC:18790",    # rescued_hgnc_id -> GATD3A
                "HGNC:1100",     # rescued_hgnc_id -> BRCA1
                "HGNC:99999999", # unresolved (no such HGNC id in fixtures)
                "HGNC:notnumeric",  # unresolved (not a real HGNC id)
            ],
        }
    )
    out, report = clean_gene_column(
        df,
        "hgnc_symbol",
        species="human",
        normalizer=normalizer,
        resolve_hgnc_id=True,
    )
    assert out["hgnc_symbol"].tolist() == [
        "BRCA1",
        "GATD3A",
        "BRCA1",
        "HGNC:99999999",
        "HGNC:notnumeric",
    ]
    assert report.resolutions == [
        "passed_through",
        "rescued_hgnc_id",
        "rescued_hgnc_id",
        "unresolved",
        "unresolved",
    ]


def test_clean_gene_column_resolve_hgnc_id_disabled_by_default(
    normalizer: GeneSymbolNormalizer,
) -> None:
    # Without the flag, HGNC:NNNNN values fall through to unresolved
    # rather than being silently coerced.
    df = pd.DataFrame({"hgnc_symbol": ["HGNC:18790"]})
    out, report = clean_gene_column(
        df, "hgnc_symbol", species="human", normalizer=normalizer
    )
    assert out["hgnc_symbol"].tolist() == ["HGNC:18790"]
    assert report.resolutions == ["unresolved"]


def test_clean_gene_column_summary_string(
    normalizer: GeneSymbolNormalizer,
) -> None:
    df = pd.DataFrame({"target_gene": ["BRCA1", "9-Sep", "WHO_KNOWS"]})
    _, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        excel_demangle=True,
    )
    s = report.summary()
    assert "passed-through 1" in s
    assert "rescued 1" in s
    assert "unresolved 1" in s
