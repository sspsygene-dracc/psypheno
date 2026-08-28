"""Validation of the `overview_matrix` table flag (#212, #222).

A flagged table always expands into heatmap columns, built from its column axis
(target genes / a phenotype column), its perturbed-gene axis and a stat column.
If any of those is missing the materializer would silently emit nothing, so the
config must fail loudly.
"""

from pathlib import Path

import pytest

from processing.types.table_to_process_config import TableToProcessConfig


def _table_json(**overrides) -> dict:
    base = {
        "table": "expanded_de",
        "description": "d",
        "in_path": "expanded_de.tsv",
        # Stamped onto every table by TablesConfig.from_yaml_root (#225). These
        # tests bypass the loader and call from_json directly, so supply them
        # here exactly the way the loader would.
        "_dataset": "expanded_dataset",
        "_deploy_to": ["dev", "prod"],
        "overview_matrix": True,
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
    assert config.overview_matrix is True


def test_default_is_off() -> None:
    config = _from_json(overview_matrix=False)
    assert config.overview_matrix is False


def test_unflagged_table_skips_validation() -> None:
    """The axis requirements only bind flagged tables — an unflagged table with
    no perturbed mapping and no stat columns must still load."""
    only_target = _table_json()["gene_mappings"][:1]
    _from_json(
        overview_matrix=False,
        gene_mappings=only_target,
        pvalue_column=None,
        fdr_column=None,
    )  # does not raise


def test_missing_stat_columns_raises() -> None:
    # Gene / long-phenotype axes need at least one stat column; one is enough
    # (perturb-FISH ships just a qval, used as the p).
    with pytest.raises(ValueError, match="a pvalue_column or fdr_column"):
        _from_json(pvalue_column=None, fdr_column=None)


@pytest.mark.parametrize("overrides", [{"pvalue_column": None}, {"fdr_column": None}])
def test_single_stat_column_is_enough(overrides: dict) -> None:
    """An expanded table needs only one of pvalue/fdr (perturb-FISH = qval)."""
    _from_json(**overrides)  # does not raise


def test_missing_perturbed_gene_mapping_raises() -> None:
    only_target = _table_json()["gene_mappings"][:1]  # target only, no perturbed
    with pytest.raises(ValueError, match="a perturbed gene_mapping"):
        _from_json(gene_mappings=only_target)


def test_no_column_axis_raises() -> None:
    # Perturbed mapping only, no target and no phenotype axis → no columns to build.
    only_perturbed = _table_json()["gene_mappings"][1:]
    with pytest.raises(ValueError, match="a column axis"):
        _from_json(gene_mappings=only_perturbed)


def test_long_phenotype_axis_is_valid() -> None:
    """A long-phenotype table: perturbed mapping + phenotype_column + a p-value."""
    only_perturbed = _table_json()["gene_mappings"][1:]
    config = _from_json(
        gene_mappings=only_perturbed,
        overview_matrix_phenotype_column="Behavioral_Parameter",
    )
    assert config.overview_matrix_phenotype_column == "behavioral_parameter"


def test_wide_phenotype_axis_requires_metric() -> None:
    only_perturbed = _table_json()["gene_mappings"][1:]
    with pytest.raises(ValueError, match="overview_matrix_metric"):
        _from_json(
            gene_mappings=only_perturbed,
            pvalue_column=None,
            fdr_column=None,
            overview_matrix_phenotype_columns=["ColA", "ColB"],
        )


def test_wide_phenotype_axis_is_valid_with_metric() -> None:
    """Wide effect tables need no p-value column but must name a metric."""
    only_perturbed = _table_json()["gene_mappings"][1:]
    config = _from_json(
        gene_mappings=only_perturbed,
        pvalue_column=None,
        fdr_column=None,
        overview_matrix_phenotype_columns=["ColA", "ColB"],
        overview_matrix_metric="signed_neglog_p",
    )
    # Wide names kept raw (materializer normalizes to read the DB column).
    assert config.overview_matrix_phenotype_columns == ["ColA", "ColB"]


def test_two_column_axes_raise() -> None:
    with pytest.raises(ValueError, match="exactly one column axis"):
        _from_json(overview_matrix_phenotype_column="param")


def test_unknown_metric_raises() -> None:
    with pytest.raises(ValueError, match="overview_matrix_metric"):
        _from_json(overview_matrix_metric="not_a_metric")
