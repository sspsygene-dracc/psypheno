"""Display column order (#240): gene columns first, then file order, unless the
table's `columnOrder` says otherwise. The web renders this order verbatim."""

from pathlib import Path

import pytest

from processing.types.table_to_process_config import (
    TableToProcessConfig,
    order_display_columns,
)

FILE_ORDER = ["condition", "gene", "log2fc", "pvalue", "fdr", "phenotype_score"]


def test_default_pins_gene_columns_then_file_order() -> None:
    # p-value / FDR are no longer pulled forward: log2fc stays before pvalue.
    assert order_display_columns(FILE_ORDER, ["gene"], [], table="t") == [
        "gene",
        "condition",
        "log2fc",
        "pvalue",
        "fdr",
        "phenotype_score",
    ]


def test_multiple_gene_columns_keep_file_order() -> None:
    cols = ["gene", "stat", "knockdown", "pvalue"]
    assert order_display_columns(cols, ["knockdown", "gene"], [], table="t") == [
        "gene",
        "knockdown",
        "stat",
        "pvalue",
    ]


def test_column_order_lists_come_first_rest_keep_default() -> None:
    assert order_display_columns(
        FILE_ORDER, ["gene"], ["pvalue", "gene"], table="t"
    ) == ["pvalue", "gene", "condition", "log2fc", "fdr", "phenotype_score"]


def test_column_order_unknown_column_raises() -> None:
    with pytest.raises(ValueError, match="not columns of the data file"):
        order_display_columns(FILE_ORDER, ["gene"], ["p_value"], table="t")


def _table_json(**overrides) -> dict:
    base = {
        "table": "t",
        "description": "d",
        "in_path": "t.tsv",
        "_dataset": "ds",
        "_deploy_to": ["dev"],
        "gene_mappings": [
            {
                "column_name": "gene",
                "link_table_name": "gene",
                "species": "human",
                "perturbed_or_target": "target",
            }
        ],
    }
    base.update(overrides)
    return base


def test_config_normalizes_column_order_names() -> None:
    config = TableToProcessConfig.from_json(
        _table_json(columnOrder=["log2FC", "P-Value"]), Path("/tmp")
    )
    assert config.column_order == ["log2fc", "p_value"]


def test_config_rejects_non_list_column_order() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        TableToProcessConfig.from_json(
            _table_json(columnOrder="log2FC"), Path("/tmp")
        )


def test_config_rejects_duplicate_column_order_names() -> None:
    with pytest.raises(ValueError, match="more than once"):
        TableToProcessConfig.from_json(
            _table_json(columnOrder=["log2FC", "log2fc"]), Path("/tmp")
        )
