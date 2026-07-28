"""Validation of the `overview_matrix_expand` table flag (#222).

An expanded modality column is built from the table's target-gene axis, its
perturbed-gene axis and both stat columns. If any of those is missing the
materializer would silently emit nothing, so the config must fail loudly.
"""

from pathlib import Path

import pytest

from processing.types.table_to_process_config import TableToProcessConfig


def _table_json(**overrides) -> dict:
    base = {
        "table": "expanded_de",
        "description": "d",
        "in_path": "expanded_de.tsv",
        "overview_matrix": True,
        "overview_matrix_expand": True,
        "pvalue_column": "P-Value",
        "fdr_column": "Adjusted_P-Value",
        "gene_mappings": [
            {
                "column_name": "target_gene",
                "link_table_name": "gene",
                "species": "human",
                "perturbed_or_target": "target",
            },
            {
                "column_name": "region_genes",
                "link_table_name": "region_gene",
                "species": "human",
                "perturbed_or_target": "perturbed",
            },
        ],
    }
    base.update(overrides)
    return base


def _from_json(**overrides) -> TableToProcessConfig:
    return TableToProcessConfig.from_json(_table_json(**overrides), Path("/tmp"))


def test_valid_expanded_table_round_trips() -> None:
    config = _from_json()
    assert config.overview_matrix_expand is True


def test_default_is_off() -> None:
    config = _from_json(overview_matrix_expand=False)
    assert config.overview_matrix_expand is False


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"overview_matrix": False}, "overview_matrix: true"),
        # Only *both* stat columns missing is fatal — one is enough (perturb-FISH
        # ships just a qval, used as the p).
        (
            {"pvalue_column": None, "fdr_column": None},
            "a pvalue_column or fdr_column",
        ),
    ],
)
def test_missing_prerequisite_raises(overrides: dict, expected: str) -> None:
    with pytest.raises(ValueError, match=expected):
        _from_json(**overrides)


@pytest.mark.parametrize("overrides", [{"pvalue_column": None}, {"fdr_column": None}])
def test_single_stat_column_is_enough(overrides: dict) -> None:
    """An expanded table needs only one of pvalue/fdr (perturb-FISH = qval)."""
    _from_json(**overrides)  # does not raise


def test_missing_gene_mapping_direction_raises() -> None:
    only_target = _table_json()["gene_mappings"][:1]
    with pytest.raises(ValueError, match="a perturbed gene_mapping"):
        _from_json(gene_mappings=only_target)

    only_perturbed = _table_json()["gene_mappings"][1:]
    with pytest.raises(ValueError, match="a target gene_mapping"):
        _from_json(gene_mappings=only_perturbed)
