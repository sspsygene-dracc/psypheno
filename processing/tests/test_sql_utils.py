"""Tests for processing.sql_utils.sanitize_identifier."""

from __future__ import annotations

import pytest

from processing.sql_utils import sanitize_identifier


@pytest.mark.parametrize(
    "name",
    [
        "foo",
        "foo_bar",
        "T1",
        "_x",
        "table_with_123",
        "ABC",
        "central_gene_id_idx",
    ],
)
def test_sanitize_identifier_accepts_alnum_underscore(name: str) -> None:
    assert sanitize_identifier(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "foo bar",
        "foo-bar",
        "foo;bar",
        "foo.bar",
        '"foo"',
        "DROP TABLE",
        "x'or'1",
    ],
)
def test_sanitize_identifier_rejects_unsafe(name: str) -> None:
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        sanitize_identifier(name)
