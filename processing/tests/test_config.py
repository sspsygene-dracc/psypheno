"""Tests for processing.config.Config and TablesConfig."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from processing.config import (
    GeneMapConfig,
    TablesConfig,
    get_sspsygene_config,
)


def _dataset_yaml(table_name: str, **overrides) -> dict:
    """A minimal but *valid* dataset config.yaml body.

    `deployTo` is mandatory since #225, so every fixture that expects a
    successful load must carry it.
    """
    body = {
        "deployTo": ["dev", "int", "prod"],
        "tables": [
            {
                "table": table_name,
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
        ],
    }
    body.update(overrides)
    return body


def _write_dataset(root: Path, name: str, table_name: str, **overrides) -> Path:
    """Write <root>/datasets/<name>/{config.yaml,data.tsv}; return the yaml path."""
    dataset_dir = root / "datasets" / name
    dataset_dir.mkdir(parents=True)
    yaml_path = dataset_dir / "config.yaml"
    yaml_path.write_text(yaml.safe_dump(_dataset_yaml(table_name, **overrides)))
    (dataset_dir / "data.tsv").write_text("gene\tx\nFoxg1\t1\n")
    return yaml_path


def _write_minimal_dataset(root: Path) -> None:
    """Drop a single config.yaml + a 1-row TSV under <root>/datasets/d1/."""
    _write_dataset(root, "d1", "d1_table")


def test_tables_config_from_yaml_root_discovers_one_dataset(tmp_path: Path) -> None:
    _write_minimal_dataset(tmp_path)
    cfg = TablesConfig.from_yaml_root(tmp_path, Path("datasets"))
    assert len(cfg.tables) == 1
    assert cfg.tables[0].table == "d1_table"
    assert cfg.tables[0].in_path == tmp_path / "datasets" / "d1" / "data.tsv"


def test_tables_config_from_yaml_root_dataset_filter(tmp_path: Path) -> None:
    _write_minimal_dataset(tmp_path)
    # Add a second dataset; --dataset must restrict to one.
    _write_dataset(tmp_path, "d2", "d2_table")

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


# ── deployTo (#225) ──────────────────────────────────────────────────────────
#
# deployTo declares which site instances a dataset may be served on. It is
# mandatory and has no default: the failure mode of a silent default is
# publishing embargoed data, so every malformed form must be a hard error that
# names the offending file.


def test_deploy_to_is_parsed_and_stamped_onto_every_table(tmp_path: Path) -> None:
    _write_dataset(tmp_path, "d1", "d1_table", deployTo=["dev", "prod"])
    cfg = TablesConfig.from_yaml_root(tmp_path, Path("datasets"))
    assert cfg.tables[0].deploy_to == frozenset({"dev", "prod"})
    # The dataset *directory* name, which nothing else in the config carries.
    assert cfg.tables[0].dataset == "d1"


def test_deploy_to_is_normalized_to_instance_order(tmp_path: Path) -> None:
    """Order in the YAML must not leak into the parsed value."""
    _write_dataset(tmp_path, "d1", "d1_table", deployTo=["prod", "dev", "int"])
    cfg = TablesConfig.from_yaml_root(tmp_path, Path("datasets"))
    assert cfg.tables[0].deploy_to == frozenset({"dev", "int", "prod"})


@pytest.mark.parametrize(
    "deploy_to, expected",
    [
        pytest.param(_MISSING := object(), "missing required", id="missing"),
        pytest.param([], "is empty", id="empty-list"),
        pytest.param("prod", "must be a list", id="scalar-string"),
        pytest.param({"dev": True}, "must be a list", id="mapping"),
        pytest.param(["dev", "staging"], "unknown instance", id="unknown-token"),
        pytest.param(["prod"], "must include `dev`", id="dev-omitted"),
        pytest.param(["int", "prod"], "must include `dev`", id="dev-omitted-multi"),
    ],
)
def test_invalid_deploy_to_hard_fails_naming_the_file(
    tmp_path: Path, deploy_to: object, expected: str
) -> None:
    overrides = {} if deploy_to is _MISSING else {"deployTo": deploy_to}
    yaml_path = _write_dataset(tmp_path, "d1", "d1_table", **overrides)
    if deploy_to is _MISSING:
        # _dataset_yaml always supplies deployTo; drop it back out.
        body = yaml.safe_load(yaml_path.read_text())
        del body["deployTo"]
        yaml_path.write_text(yaml.safe_dump(body))

    with pytest.raises(ValueError) as excinfo:
        TablesConfig.from_yaml_root(tmp_path, Path("datasets"))

    message = str(excinfo.value)
    assert expected in message
    # Naming the file is the whole point — a wrangler must know which one.
    assert str(yaml_path) in message


def test_empty_config_yaml_is_an_error(tmp_path: Path) -> None:
    """An empty file used to be skipped silently, which would let a dataset
    with no declared destination sit on disk unnoticed."""
    dataset_dir = tmp_path / "datasets" / "d1"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "config.yaml").write_text("")
    with pytest.raises(ValueError, match="is empty"):
        TablesConfig.from_yaml_root(tmp_path, Path("datasets"))


def test_deploy_to_validated_even_with_no_tables(tmp_path: Path) -> None:
    """An empty `tables:` list must not skip deployTo validation — the check
    runs per file, not per table."""
    _write_dataset(tmp_path, "d1", "d1_table", tables=[], deployTo=["prod"])
    with pytest.raises(ValueError, match="must include `dev`"):
        TablesConfig.from_yaml_root(tmp_path, Path("datasets"))


def test_unknown_top_level_key_warns_but_loads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A `deployto:` / `deplyTo:` typo must be visible rather than silently
    disarming the flag. It is a warning, not an error, because the real
    deployTo is still present and valid."""
    _write_dataset(tmp_path, "d1", "d1_table", deploryTo=["dev"])
    with caplog.at_level("WARNING", logger="processing.config"):
        cfg = TablesConfig.from_yaml_root(tmp_path, Path("datasets"))
    assert len(cfg.tables) == 1
    assert "deploryTo" in caplog.text
    assert "unknown top-level YAML key" in caplog.text


def test_table_level_deploy_to_is_not_recognized(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """deployTo is a *dataset*-level key. Putting it under a table must trip
    the existing per-table unknown-key warning rather than appear to work."""
    body = _dataset_yaml("d1_table")
    body["tables"][0]["deployTo"] = ["dev", "prod"]
    dataset_dir = tmp_path / "datasets" / "d1"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "config.yaml").write_text(yaml.safe_dump(body))
    (dataset_dir / "data.tsv").write_text("gene\tx\nFoxg1\t1\n")

    with caplog.at_level("WARNING"):
        cfg = TablesConfig.from_yaml_root(tmp_path, Path("datasets"))
    assert "deployTo" in caplog.text
    assert "unknown YAML key" in caplog.text
    # The dataset-level value is what actually took effect.
    assert cfg.tables[0].deploy_to == frozenset({"dev", "int", "prod"})


def test_legacy_tables_list_is_rejected() -> None:
    """A bare `tables` list in config.json has no config.yaml and therefore no
    deployTo, so it can't produce a table with a declared destination."""
    with pytest.raises(ValueError, match="legacy `tables` list"):
        TablesConfig.from_legacy_tables_list([], Path("/tmp"))


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
    assert {t.table for t in config.tables_config.tables} == {
        "mini_perturb_deg",
        "mini_embargoed_deg",
    }


def test_config_tables_carry_dataset_and_deploy_to(mini_fixture: Path) -> None:
    """The two fixture datasets differ in deployTo on purpose (#225)."""
    config = get_sspsygene_config()
    by_table = {t.table: t for t in config.tables_config.tables}
    assert by_table["mini_perturb_deg"].dataset == "mini_perturb"
    assert by_table["mini_perturb_deg"].deploy_to == frozenset({"dev", "prod"})
    assert by_table["mini_embargoed_deg"].dataset == "mini_embargoed"
    assert by_table["mini_embargoed_deg"].deploy_to == frozenset({"dev"})


def test_config_dataset_arg_restricts_tables(mini_fixture: Path) -> None:
    config = get_sspsygene_config(dataset="mini_perturb")
    assert {t.table for t in config.tables_config.tables} == {"mini_perturb_deg"}


def test_config_global_config_loaded(mini_fixture: Path) -> None:
    config = get_sspsygene_config()
    assert config.global_config.get("assayTypes", {}).get("perturbation") == (
        "Perturbation Screen"
    )
