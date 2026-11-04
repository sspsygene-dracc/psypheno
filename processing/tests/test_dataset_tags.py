"""Dataset tags: model_system / anatomy / stage parsing, overrides, validation."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from processing import dataset_tags
from processing.config import TablesConfig
from processing.dataset_tags import DatasetTags, uberon_terms

BRAIN = "UBERON:0000955"
NEOCORTEX = "UBERON:0001950"
CEREBRAL_CORTEX = "UBERON:0000956"
KIDNEY = "UBERON:0002113"


def _table(name: str, **extra) -> dict:
    body = {
        "table": name,
        "description": "tags test fixture table",
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
    body.update(extra)
    return body


def _load(tmp_path: Path, tables: list[dict] | None = None, **dataset_keys):
    dataset_dir = tmp_path / "datasets" / "d1"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    body = {"deployTo": ["dev"], "tables": tables or [_table("t1")]}
    body.update(dataset_keys)
    (dataset_dir / "config.yaml").write_text(yaml.safe_dump(body))
    (dataset_dir / "data.tsv").write_text("gene\tBrodmann Area\nFoxg1\tBA9\n")
    return TablesConfig.from_yaml_root(tmp_path, Path("datasets"))


@pytest.fixture
def require_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dataset_tags, "REQUIRE_DATASET_TAGS", True)


# ── The vendored UBERON list ──────────────────────────────────────────────


def test_vendored_uberon_list_has_the_spec_terms() -> None:
    terms = uberon_terms()
    assert terms[BRAIN].label == "brain"
    assert terms[NEOCORTEX].label == "neocortex"
    assert terms[CEREBRAL_CORTEX].label == "cerebral cortex"
    assert terms["UBERON:0001851"].label == "cortex"
    assert terms["UBERON:0000468"].label == "multicellular organism"
    assert terms[KIDNEY].label == "kidney"
    # Ancestor closure: neocortex is (part of) cerebral cortex, part of brain.
    assert {CEREBRAL_CORTEX, BRAIN} <= terms[NEOCORTEX].ancestors
    assert NEOCORTEX not in terms[NEOCORTEX].ancestors


# ── Parsing and override resolution ──────────────────────────────────────


def test_dataset_level_tags_reach_every_table(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        tables=[_table("t1"), _table("t2")],
        model_system="ineurons",
        anatomy=[BRAIN],
        stage="in_vitro",
        stage_detail="NGN2 day 28",
    )
    for t in cfg.tables:
        assert t.tags == DatasetTags(
            model_system="ineurons",
            anatomy=(BRAIN,),
            stage="in_vitro",
            stage_detail="NGN2 day 28",
        )


def test_table_overrides_replace_dataset_values_per_key(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        tables=[
            _table("t1"),
            _table("t2", model_system="organoid", anatomy=[NEOCORTEX]),
        ],
        model_system="ineurons",
        anatomy=[BRAIN],
        stage="in_vitro",
    )
    t1, t2 = cfg.tables
    assert (t1.tags.model_system, t1.tags.anatomy) == ("ineurons", (BRAIN,))
    assert (t2.tags.model_system, t2.tags.anatomy) == ("organoid", (NEOCORTEX,))
    # stage not overridden -> inherited.
    assert t2.tags.stage == "in_vitro"


def test_anatomy_closure_and_labels() -> None:
    tags = DatasetTags(model_system="postmortem", anatomy=(NEOCORTEX,))
    assert tags.anatomy_terms() == [{"id": NEOCORTEX, "label": "neocortex"}]
    closure = tags.anatomy_closure()
    assert NEOCORTEX in closure and CEREBRAL_CORTEX in closure and BRAIN in closure
    assert KIDNEY not in closure


# ── Always-errors: unknown values ────────────────────────────────────────


@pytest.mark.parametrize(
    "keys, match",
    [
        ({"model_system": "iNeurons"}, "model_system"),
        ({"model_system": "in_vivo", "stage": "juvenile"}, "stage"),
        ({"model_system": "in_vivo", "anatomy": ["UBERON:9999999"]}, "UBERON:9999999"),
        ({"model_system": "in_vivo", "anatomy": ["brain"]}, "brain"),
        ({"model_system": "in_vivo", "anatomy": [BRAIN, BRAIN]}, "more than once"),
        ({"model_system": "in_vivo", "anatomy": {"id": BRAIN}}, "list of UBERON"),
        ({"model_system": "in_vivo", "anatomy": [BRAIN], "stage_detail": ""}, "stage_detail"),
    ],
)
def test_unknown_dataset_level_values_fail_naming_the_file(
    tmp_path: Path, keys: dict, match: str
) -> None:
    with pytest.raises(ValueError, match=match) as exc:
        _load(tmp_path, **keys)
    assert "config.yaml" in str(exc.value)


def test_unknown_table_level_values_fail(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="UBERON:0000000"):
        _load(
            tmp_path,
            tables=[_table("t1", anatomy=["UBERON:0000000"])],
            model_system="in_vivo",
            anatomy=[BRAIN],
        )


def test_unknown_values_fail_even_with_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dataset_tags, "REQUIRE_DATASET_TAGS", False)
    with pytest.raises(ValueError):
        dataset_tags.validate_tag_values({"model_system": "zoo"}, context="x")


# ── Completeness: warning during the transition, error once switched ────


def test_missing_tags_warn_while_switch_is_off(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dataset_tags, "REQUIRE_DATASET_TAGS", False)
    with caplog.at_level(logging.WARNING):
        cfg = _load(tmp_path)
    assert cfg.tables[0].tags == DatasetTags()
    assert "no model_system" in caplog.text
    assert "no anatomy terms" in caplog.text


def test_missing_model_system_errors_when_required(
    tmp_path: Path, require_tags: None
) -> None:
    with pytest.raises(ValueError, match="no model_system"):
        _load(tmp_path, anatomy=[BRAIN])


def test_missing_anatomy_errors_when_required(
    tmp_path: Path, require_tags: None
) -> None:
    with pytest.raises(ValueError, match="no anatomy terms"):
        _load(tmp_path, model_system="organoid")


def test_curated_needs_no_anatomy(tmp_path: Path, require_tags: None) -> None:
    cfg = _load(tmp_path, model_system="curated")
    assert cfg.tables[0].tags.model_system == "curated"
    assert cfg.tables[0].tags.anatomy == ()


def test_table_override_to_curated_drops_anatomy_requirement(
    tmp_path: Path, require_tags: None
) -> None:
    cfg = _load(
        tmp_path,
        tables=[_table("t1", model_system="curated")],
        model_system="curated",
    )
    assert cfg.tables[0].tags.model_system == "curated"


def test_fully_tagged_dataset_loads_with_switch_on(
    tmp_path: Path, require_tags: None
) -> None:
    cfg = _load(tmp_path, model_system="cell_line", anatomy=[KIDNEY])
    assert cfg.tables[0].tags.anatomy == (KIDNEY,)


# ── anatomy_column ──────────────────────────────────────────────────────


def test_anatomy_column_is_normalized(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        tables=[_table("t1", anatomy_column="Brodmann Area")],
        model_system="postmortem",
        anatomy=[NEOCORTEX],
    )
    assert cfg.tables[0].tags.anatomy_column == "brodmann_area"


def test_anatomy_column_must_exist_in_the_data(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        tables=[_table("t1", anatomy_column="region")],
        model_system="postmortem",
        anatomy=[NEOCORTEX],
    )
    with pytest.raises(ValueError, match="anatomy_column 'region' not found"):
        cfg.tables[0].load_data_table()


def test_anatomy_column_is_table_level_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        cfg = _load(
            tmp_path,
            model_system="postmortem",
            anatomy=[NEOCORTEX],
            anatomy_column="brodmann_area",
        )
    assert "unknown top-level YAML key" in caplog.text
    assert cfg.tables[0].tags.anatomy_column is None


def test_tag_keys_are_recognized_without_unknown_key_warnings(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        _load(
            tmp_path,
            tables=[_table("t1", stage="adult", anatomy_column="brodmann_area")],
            model_system="postmortem",
            anatomy=[NEOCORTEX],
        )
    assert "unknown" not in caplog.text


# ── Link-only datasets ──────────────────────────────────────────────────


def test_link_only_dataset_carries_tags(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "datasets" / "lo"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "deployTo": ["dev"],
                "publication": {"doi": "10.1/x"},
                "links": ["https://example.org"],
                "model_system": "in_vivo",
                "anatomy": [BRAIN],
                "stage": "adult",
            }
        )
    )
    cfg = TablesConfig.from_yaml_root(tmp_path, Path("datasets"))
    assert cfg.link_only[0].tags == DatasetTags(
        model_system="in_vivo", anatomy=(BRAIN,), stage="adult"
    )
