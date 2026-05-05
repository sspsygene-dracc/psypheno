"""Tests for the preprocessing Pipeline / Step / Tracker library."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from processing.preprocessing import (
    EnsemblToSymbolMapper,
    GeneSymbolNormalizer,
    MANUAL_ALIASES_HUMAN,
    Pipeline,
    Tracker,
    copy_file,
)


def test_tracker_write_sidecar_round_trip(tmp_path: Path) -> None:
    tracker = Tracker()
    tracker.note_input("raw.csv")
    tracker.record("read_csv", table="cleaned.csv", source="raw.csv")
    tracker.record(
        "clean_gene_column",
        table="cleaned.csv",
        column="target_gene",
        species="human",
        counts={"passed_through": 10, "rescued_excel": 2},
    )
    tracker.record(
        "drop_columns", table="cleaned.csv", columns=["_target_gene_resolution"]
    )

    out = tmp_path / "cleaned.csv"
    sidecar = tracker.write_sidecar(out)

    assert sidecar == tmp_path / "cleaned.csv.preprocessing.yaml"
    loaded = yaml.safe_load(sidecar.read_text())
    assert loaded["output"] == "cleaned.csv"
    assert loaded["inputs"] == ["raw.csv"]
    assert "generated" in loaded
    actions = loaded["actions"]
    assert [a["step"] for a in actions] == [
        "read_csv",
        "clean_gene_column",
        "drop_columns",
    ]
    assert actions[1]["counts"]["passed_through"] == 10
    assert actions[2]["columns"] == ["_target_gene_resolution"]
    # No `tables:` dict in the new flat schema.
    assert "tables" not in loaded


def test_pipeline_clean_gene_then_drop(
    normalizer: GeneSymbolNormalizer,
    tmp_path: Path,
) -> None:
    """End-to-end: read CSV → clean gene column → drop resolution col → write."""
    raw = tmp_path / "raw.csv"
    pd.DataFrame(
        {"target_gene": ["BRCA1", "9-Sep", "WHO_KNOWS"], "x": [1, 2, 3]}
    ).to_csv(raw, index=False)
    out_path = tmp_path / "cleaned.csv"

    tracker = Tracker()
    (
        Pipeline("cleaned.csv", tracker=tracker, normalizer=normalizer)
        .read_csv(raw)
        .clean_gene("target_gene", species="human", excel_demangle=True)
        .drop_columns(["_target_gene_resolution"])
        .write_csv(out_path)
        .run()
    )

    df = pd.read_csv(out_path, dtype=str)
    assert df["target_gene"].tolist() == ["BRCA1", "SEPTIN9", "WHO_KNOWS"]
    # Raw column kept by default (provenance for end users).
    assert "target_gene_raw" in df.columns
    # Resolution column was dropped via the tracked step.
    assert "_target_gene_resolution" not in df.columns

    actions = tracker.actions
    assert [a.step for a in actions] == [
        "read_csv",
        "clean_gene_column",
        "drop_columns",
        "write_csv",
    ]
    clean = next(a for a in actions if a.step == "clean_gene_column")
    assert clean.summary["column"] == "target_gene"
    assert clean.summary["species"] == "human"
    assert clean.summary["counts"]["rescued_excel"] == 1
    assert clean.summary["counts"]["unresolved"] == 1
    assert "WHO_KNOWS" in clean.summary["sample_unresolved"]


def test_pipeline_dropna_records_before_after(
    normalizer: GeneSymbolNormalizer, tmp_path: Path
) -> None:
    raw = tmp_path / "raw.csv"
    # Use literal "EMPTY_STR" placeholder + a NaN; pandas reads "" as NaN by
    # default so the only way to keep an empty-but-present string distinct is
    # to write a non-empty token then strip-filter it.
    pd.DataFrame(
        {"hgnc_symbol": ["BRCA1", None, "TP53", "   "], "x": [1, 2, 3, 4]}
    ).to_csv(raw, index=False)
    out = tmp_path / "out.csv"

    tracker = Tracker()
    (
        Pipeline("out.csv", tracker=tracker, normalizer=normalizer)
        .read_csv(raw)
        .dropna(["hgnc_symbol"])
        .filter_rows(
            lambda d: d["hgnc_symbol"].astype(str).str.strip() != "",  # type: ignore
            description="non-empty hgnc_symbol",
        )
        .write_csv(out)
        .run()
    )

    df = pd.read_csv(out, dtype=str)
    assert df["hgnc_symbol"].tolist() == ["BRCA1", "TP53"]

    dropna = next(a for a in tracker.actions if a.step == "dropna")
    assert dropna.summary["rows_before"] == 4
    # NaN dropped by dropna; whitespace-only string still present at this stage.
    assert dropna.summary["rows_after"] == 3
    assert dropna.summary["dropped"] == 1

    fr = next(a for a in tracker.actions if a.step == "filter_rows")
    assert fr.summary["description"] == "non-empty hgnc_symbol"
    assert fr.summary["dropped"] == 1


def test_pipeline_rename_and_reorder(
    normalizer: GeneSymbolNormalizer, tmp_path: Path
) -> None:
    raw = tmp_path / "raw.csv"
    pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6]}).to_csv(raw, index=False)
    out = tmp_path / "out.csv"

    tracker = Tracker()
    (
        Pipeline("out.csv", tracker=tracker, normalizer=normalizer)
        .read_csv(raw)
        .rename({"a": "alpha", "b": "beta", "missing": "ignored"})
        .reorder(["beta", "alpha", "c"])
        .write_csv(out)
        .run()
    )

    df = pd.read_csv(out, dtype=str)
    assert df.columns.tolist() == ["beta", "alpha", "c"]

    rename = next(a for a in tracker.actions if a.step == "rename")
    # Only applied (present) renames are recorded.
    assert rename.summary["mapping"] == {"a": "alpha", "b": "beta"}

    reorder = next(a for a in tracker.actions if a.step == "reorder")
    assert reorder.summary["columns"] == ["beta", "alpha", "c"]


def test_pipeline_transform_column_records_description(
    normalizer: GeneSymbolNormalizer, tmp_path: Path
) -> None:
    raw = tmp_path / "raw.csv"
    pd.DataFrame({"name": ["ABALON.", "SGK494.", "BRCA1"]}).to_csv(raw, index=False)
    out = tmp_path / "out.csv"

    tracker = Tracker()
    (
        Pipeline("out.csv", tracker=tracker, normalizer=normalizer)
        .read_csv(raw)
        .transform_column(
            "name",
            lambda s: s.str.rstrip("."),  # type: ignore
            description="strip trailing dots from MarkerName",
        )
        .write_csv(out)
        .run()
    )

    df = pd.read_csv(out, dtype=str)
    assert df["name"].tolist() == ["ABALON", "SGK494", "BRCA1"]

    rec = next(a for a in tracker.actions if a.step == "transform_column")
    assert rec.summary["description"] == "strip trailing dots from MarkerName"
    assert rec.summary["rows_changed"] == 2


def test_pipeline_insert_column(
    normalizer: GeneSymbolNormalizer, tmp_path: Path
) -> None:
    raw = tmp_path / "raw.csv"
    pd.DataFrame({"x": [1, 2, 3]}).to_csv(raw, index=False)
    out = tmp_path / "out.csv"

    tracker = Tracker()
    (
        Pipeline("out.csv", tracker=tracker, normalizer=normalizer)
        .read_csv(raw)
        .insert_column("perturbation", "16p11del", position=0)
        .write_csv(out)
        .run()
    )

    df = pd.read_csv(out, dtype=str)
    assert df.columns.tolist() == ["perturbation", "x"]
    assert df["perturbation"].tolist() == ["16p11del", "16p11del", "16p11del"]

    rec = next(a for a in tracker.actions if a.step == "insert_column")
    assert rec.summary["column"] == "perturbation"
    assert rec.summary["value"] == "16p11del"


def test_copy_file_records_pass_through(tmp_path: Path) -> None:
    src = tmp_path / "patient_list.tsv"
    src.write_text("id\tname\n1\tx\n")
    dst = tmp_path / "out" / "patient_list.tsv"

    tracker = Tracker()
    copy_file(src, dst, tracker=tracker)

    assert dst.read_text() == src.read_text()
    rec = tracker.actions[0]
    assert rec.step == "copy_file"
    assert rec.table == "patient_list.tsv"
    assert rec.summary["source"] == "patient_list.tsv"

    sidecar = dst.parent / "patient_list.tsv.preprocessing.yaml"
    assert sidecar.exists()
    loaded = yaml.safe_load(sidecar.read_text())
    assert loaded["output"] == "patient_list.tsv"
    assert loaded["inputs"] == ["patient_list.tsv"]
    assert [a["step"] for a in loaded["actions"]] == ["copy_file"]


def test_pipeline_keeps_resolution_column_by_default(
    normalizer: GeneSymbolNormalizer, tmp_path: Path
) -> None:
    """#150: don't drop `_<col>_resolution` silently — it carries provenance."""
    raw = tmp_path / "raw.csv"
    pd.DataFrame({"target_gene": ["BRCA1"]}).to_csv(raw, index=False)
    out = tmp_path / "out.csv"

    tracker = Tracker()
    (
        Pipeline("out.csv", tracker=tracker, normalizer=normalizer)
        .read_csv(raw)
        .clean_gene("target_gene", species="human")
        .write_csv(out)
        .run()
    )

    df = pd.read_csv(out, dtype=str)
    assert "_target_gene_resolution" in df.columns
    assert "target_gene_raw" in df.columns


def test_pipeline_run_without_write_raises(
    normalizer: GeneSymbolNormalizer, tmp_path: Path
) -> None:
    """A pipeline that has no read step is malformed; cleaner error than KeyError."""
    raw = tmp_path / "raw.csv"
    pd.DataFrame({"a": [1]}).to_csv(raw, index=False)

    tracker = Tracker()
    pipe = Pipeline("out.csv", tracker=tracker, normalizer=normalizer)
    # No read step — clean_gene should fail with the helpful message.
    pipe.clean_gene("a", species="human")
    with pytest.raises(ValueError, match="requires a DataFrame"):
        pipe.run()


def test_two_pipelines_share_one_tracker(
    normalizer: GeneSymbolNormalizer, tmp_path: Path
) -> None:
    """Two outputs → two per-output sidecars, each with its own scoped inputs."""
    raw1 = tmp_path / "a.csv"
    raw2 = tmp_path / "b.csv"
    pd.DataFrame({"target_gene": ["BRCA1"]}).to_csv(raw1, index=False)
    pd.DataFrame({"target_gene": ["TP53"]}).to_csv(raw2, index=False)

    tracker = Tracker()
    for in_path, out_name in [(raw1, "a_clean.csv"), (raw2, "b_clean.csv")]:
        (
            Pipeline(out_name, tracker=tracker, normalizer=normalizer)
            .read_csv(in_path)
            .clean_gene("target_gene", species="human")
            .write_csv(tmp_path / out_name)
            .run()
        )

    sidecar_a = tmp_path / "a_clean.csv.preprocessing.yaml"
    sidecar_b = tmp_path / "b_clean.csv.preprocessing.yaml"
    assert sidecar_a.exists() and sidecar_b.exists()
    loaded_a = yaml.safe_load(sidecar_a.read_text())
    loaded_b = yaml.safe_load(sidecar_b.read_text())
    # Per-output inputs are scoped to that pipeline's read step, not the
    # tracker's global inputs list (which contains both a.csv and b.csv).
    assert loaded_a["output"] == "a_clean.csv"
    assert loaded_a["inputs"] == ["a.csv"]
    assert loaded_b["output"] == "b_clean.csv"
    assert loaded_b["inputs"] == ["b.csv"]
    # Each sidecar contains only its own pipeline's actions.
    assert all(
        a["step"] != "read_csv" or a["source"] == "a.csv"
        for a in loaded_a["actions"]
    )
    assert all(
        a["step"] != "read_csv" or a["source"] == "b.csv"
        for a in loaded_b["actions"]
    )


def test_write_concat_emits_sidecar_with_explicit_inputs(tmp_path: Path) -> None:
    """hsc-asd-style multi-sheet → one combined output with explicit inputs."""
    out = tmp_path / "supp3_combined.tsv"
    out.write_text("col\nval\n")
    tracker = Tracker()
    tracker.note_input("supp3.xlsx")
    tracker.note_input("supp12.xlsx")
    # Sub-pipeline records (would be written by Pipeline.run normally) tagged
    # with sub-pipeline names; these must NOT leak into the combined sidecar.
    tracker.record("clean_gene_column", table="supp3:Adult_PFC", column="hgnc_symbol")

    sidecar = tracker.write_concat(
        out,
        inputs=["supp3.xlsx"],
        sheets=2,
        rows=42,
    )

    assert sidecar == tmp_path / "supp3_combined.tsv.preprocessing.yaml"
    loaded = yaml.safe_load(sidecar.read_text())
    assert loaded["output"] == "supp3_combined.tsv"
    # Explicit inputs win over the tracker's global list (which has supp12 too).
    assert loaded["inputs"] == ["supp3.xlsx"]
    actions = loaded["actions"]
    assert [a["step"] for a in actions] == ["concat_and_write"]
    assert actions[0]["sheets"] == 2
    assert actions[0]["rows"] == 42
    assert actions[0]["destination"] == "supp3_combined.tsv"


def test_clean_gene_with_ensembl_mapper(
    normalizer: GeneSymbolNormalizer,
    ensembl_mapper: EnsemblToSymbolMapper,
    tmp_path: Path,
) -> None:
    """Ensure resolve_via_ensembl_map flag plumbs through the pipeline."""
    raw = tmp_path / "raw.csv"
    # Use one ENSG that's in the fixture's hgnc_stub mapping.
    pd.DataFrame({"target_gene": ["ENSG00000012048"]}).to_csv(raw, index=False)
    out = tmp_path / "out.csv"

    tracker = Tracker()
    (
        Pipeline(
            "out.csv",
            tracker=tracker,
            normalizer=normalizer,
            ensembl_mapper=ensembl_mapper,
        )
        .read_csv(raw)
        .clean_gene(
            "target_gene",
            species="human",
            resolve_via_ensembl_map=True,
        )
        .write_csv(out)
        .run()
    )

    df = pd.read_csv(out, dtype=str)
    # The fixture maps ENSG00000012048 → BRCA1 (see fixtures/hgnc_stub.txt).
    assert df["target_gene"].tolist() == ["BRCA1"]
    rec = next(a for a in tracker.actions if a.step == "clean_gene_column")
    assert rec.summary["counts"].get("rescued_ensembl_map") == 1


def test_resolve_via_ensembl_map_silent_skip_no_mapper(
    normalizer: GeneSymbolNormalizer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without SSPSYGENE_DATA_DIR, Pipeline can't auto-instantiate the
    # mapper. The resolver silently skips rather than raising.
    monkeypatch.delenv("SSPSYGENE_DATA_DIR", raising=False)
    raw = tmp_path / "raw.csv"
    out_path = tmp_path / "out.csv"
    pd.DataFrame({"target_gene": ["ENSG00000012048"]}).to_csv(raw, index=False)

    tracker = Tracker()
    (
        Pipeline("out.csv", tracker=tracker, normalizer=normalizer)
        .read_csv(raw)
        .clean_gene("target_gene", species="human")
        .write_csv(out_path)
        .run()
    )

    # ENSG falls through to the silencer (no mapper to rescue it).
    written = pd.read_csv(out_path)
    assert written["target_gene"].tolist() == ["ENSG00000012048"]
    assert written["_target_gene_resolution"].tolist() == ["non_symbol_ensembl_human"]


def test_pipeline_auto_instantiates_mappers_from_env(
    normalizer: GeneSymbolNormalizer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If SSPSYGENE_DATA_DIR points at a usable homology dir, Pipeline
    # auto-instantiates EnsemblToSymbolMapper and GencodeCloneIndex
    # without the caller having to pass them.
    fixtures = Path(__file__).parent / "fixtures"
    # Stage the homology fixtures under a `homology/` subdir to match
    # the env-relative paths used by from_env().
    homology = tmp_path / "homology"
    homology.mkdir()
    (homology / "hgnc_complete_set.txt").write_text(
        (fixtures / "hgnc_stub.txt").read_text()
    )
    (homology / "MGI_EntrezGene.rpt").write_text(
        (fixtures / "mgi_stub.rpt").read_text()
    )
    (homology / "HGNC_AllianceHomology.rpt").write_text(
        (fixtures / "alliance_homology_stub.rpt").read_text()
    )
    (homology / "gencode_clone_map.tsv").write_text(
        (fixtures / "gencode_clone_map_stub.tsv").read_text()
    )
    monkeypatch.setenv("SSPSYGENE_DATA_DIR", str(tmp_path))

    raw = tmp_path / "raw.csv"
    out_path = tmp_path / "out.csv"
    pd.DataFrame({"target_gene": ["BRCA1", "RP11-100A1.1"]}).to_csv(raw, index=False)

    tracker = Tracker()
    (
        Pipeline("out.csv", tracker=tracker, normalizer=normalizer)
        .read_csv(raw)
        .clean_gene("target_gene", species="human")
        .write_csv(out_path)
        .run()
    )

    written = pd.read_csv(out_path)
    # RP11-100A1.1 -> BRCA1 via the GencodeCloneIndex auto-loaded from env.
    assert written["target_gene"].tolist() == ["BRCA1", "BRCA1"]
    assert written["_target_gene_resolution"].tolist() == [
        "passed_through",
        "rescued_gencode_clone_hgnc_symbol",
    ]


def test_manual_aliases_human_constant_unchanged() -> None:
    """The cross-dataset alias superset; wranglers extend it per-dataset."""
    assert MANUAL_ALIASES_HUMAN == {
        "NOV": "CCN3",
        "MUM1": "PWWP3A",
        "QARS": "QARS1",
        "SARS": "SARS1",
        "TAZ": "TAFAZZIN",
    }
