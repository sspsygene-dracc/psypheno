"""Tests for processing.config.Config and TablesConfig."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from processing.config import (
    Config,
    GeneMapConfig,
    TablesConfig,
    get_sspsygene_config,
)


def _write_minimal_dataset(root: Path) -> None:
    """Drop a single config.yaml + a 1-row TSV under <root>/datasets/d1/."""
    (root / "datasets").mkdir()
    (root / "datasets" / "d1").mkdir()
    (root / "datasets" / "d1" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "tables": [
                    {
                        "table": "d1_table",
                        "description": "config test fixture table",
                        "in_path": "data.tsv",
                        "separator": "\t",
                        "gene_mappings": [
                            {
                                "column_name": "gene",
                                "link_table_name": "gene",
                                "species": "mouse",
                                "perturbed_or_target": "perturbed",
                            }
                        ],
                    }
                ]
            }
        )
    )
    (root / "datasets" / "d1" / "data.tsv").write_text("gene\tx\nFoxg1\t1\n")


def test_tables_config_from_yaml_root_discovers_one_dataset(tmp_path: Path) -> None:
    _write_minimal_dataset(tmp_path)
    cfg = TablesConfig.from_yaml_root(tmp_path, Path("datasets"))
    assert len(cfg.tables) == 1
    assert cfg.tables[0].table == "d1_table"
    assert cfg.tables[0].in_path == tmp_path / "datasets" / "d1" / "data.tsv"


def test_tables_config_from_yaml_root_dataset_filter(tmp_path: Path) -> None:
    _write_minimal_dataset(tmp_path)
    # Add a second dataset; --dataset must restrict to one.
    (tmp_path / "datasets" / "d2").mkdir()
    (tmp_path / "datasets" / "d2" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "tables": [
                    {
                        "table": "d2_table",
                        "description": "second fixture table",
                        "in_path": "data.tsv",
                        "separator": "\t",
                        "gene_mappings": [
                            {
                                "column_name": "gene",
                                "link_table_name": "gene",
                                "species": "mouse",
                                "perturbed_or_target": "perturbed",
                            }
                        ],
                    }
                ]
            }
        )
    )
    (tmp_path / "datasets" / "d2" / "data.tsv").write_text("gene\nFoxg1\n")

    cfg_full = TablesConfig.from_yaml_root(tmp_path, Path("datasets"))
    assert {t.table for t in cfg_full.tables} == {"d1_table", "d2_table"}

    cfg_one = TablesConfig.from_yaml_root(tmp_path, Path("datasets"), dataset="d1")
    assert {t.table for t in cfg_one.tables} == {"d1_table"}


def test_tables_config_unknown_dataset_raises(tmp_path: Path) -> None:
    _write_minimal_dataset(tmp_path)
    with pytest.raises(FileNotFoundError, match="config.yaml not found"):
        TablesConfig.from_yaml_root(tmp_path, Path("datasets"), dataset="nope")


def test_tables_config_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="tables_root directory does not exist"):
        TablesConfig.from_yaml_root(tmp_path, Path("does/not/exist"))


def test_tables_config_bad_yaml_includes_path(tmp_path: Path) -> None:
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / "d1").mkdir()
    bad_yaml = tmp_path / "datasets" / "d1" / "config.yaml"
    bad_yaml.write_text(":\n :\n -bad: [unterminated")
    with pytest.raises(ValueError, match=str(bad_yaml)):
        TablesConfig.from_yaml_root(tmp_path, Path("datasets"))


def test_config_resolves_paths_relative_to_data_dir(
    mini_fixture: Path,
) -> None:
    """`Config` consumes SSPSYGENE_DATA_DIR + SSPSYGENE_CONFIG_JSON env vars
    and resolves out_db / gene_map_files relative to the data dir."""
    config = get_sspsygene_config()

    assert config.base_dir == mini_fixture
    assert config.out_db == mini_fixture / "db" / "mini.db"
    assert isinstance(config.gene_map_config, GeneMapConfig)
    assert (
        config.gene_map_config.hgnc_file
        == mini_fixture / "homology" / "hgnc_complete_set.txt"
    )
    # The mini-dataset fixture only ships one dataset.
    assert {t.table for t in config.tables_config.tables} == {"mini_perturb_deg"}


def test_config_dataset_arg_restricts_tables(mini_fixture: Path) -> None:
    config = get_sspsygene_config(dataset="mini_perturb")
    assert {t.table for t in config.tables_config.tables} == {"mini_perturb_deg"}


def test_config_global_config_loaded(mini_fixture: Path) -> None:
    config = get_sspsygene_config()
    assert config.global_config.get("assayTypes", {}).get("perturbation") == (
        "Perturbation Screen"
    )
