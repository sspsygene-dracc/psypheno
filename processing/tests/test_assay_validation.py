"""load-db rejects assay keys that globals.yaml's assayTypes doesn't define, so a
new experiment type can't half-exist (no label, no matrix modality)."""

from types import SimpleNamespace

import pytest

from processing.sq_load import validate_assay_keys

ASSAYS = {"expression": "Gene Expression", "ppi": "Protein-Protein Interaction"}


def _table(name: str, *assays: str) -> SimpleNamespace:
    return SimpleNamespace(table=name, assay=list(assays))


def test_known_assays_pass() -> None:
    validate_assay_keys(
        [_table("a", "expression"), _table("b", "ppi")],  # type: ignore[list-item]
        ASSAYS,
        [{"key": "ppi", "assayTypes": ["ppi"]}, {"key": "morph", "assayTypes": []}],
    )


def test_unknown_table_assay_raises() -> None:
    with pytest.raises(ValueError, match="table b: assay 'protein_interaction'"):
        validate_assay_keys(
            [_table("b", "protein_interaction")],  # type: ignore[list-item]
            ASSAYS,
            [],
        )


def test_unknown_modality_assay_raises() -> None:
    with pytest.raises(ValueError, match="modality ppi: assayTypes entry 'pp1'"):
        validate_assay_keys([], ASSAYS, [{"key": "ppi", "assayTypes": ["pp1"]}])
