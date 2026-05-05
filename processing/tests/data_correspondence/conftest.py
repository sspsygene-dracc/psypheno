"""Shared fixtures for data-correspondence tests (#113)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from .helpers import (
    PrimaryTable,
    db_path,
    enumerate_primary_tables,
    open_db_readonly,
)


@pytest.fixture(scope="session")
def primary_tables() -> list[PrimaryTable]:
    return enumerate_primary_tables()


def _id_for(t: PrimaryTable) -> str:
    return f"{t.dataset}/{t.table_name}"


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Auto-parametrize any test that takes a `table` fixture.

    Lets every test family in this directory iterate the same canonical
    list with stable ids without each module repeating the parametrize.
    Tests that already parametrize `table` themselves (e.g. paired with a
    row index) opt out by carrying a `pytest.mark.parametrize` on the
    function — the manual marker takes precedence.
    """
    if "table" not in metafunc.fixturenames:
        return
    for marker in metafunc.definition.iter_markers("parametrize"):
        argnames = marker.args[0] if marker.args else ""
        argname_set = (
            set(argnames) if isinstance(argnames, (list, tuple))
            else {p.strip() for p in str(argnames).split(",")}
        )
        if "table" in argname_set:
            return
    tables = enumerate_primary_tables()
    metafunc.parametrize("table", tables, ids=[_id_for(t) for t in tables])


@pytest.fixture(scope="session")
def db() -> Iterator[sqlite3.Connection]:
    """Open the live DB read-only; skip the test if it's missing."""
    if not db_path().exists():
        pytest.skip(f"DB not present at {db_path()} — skipping DB-dependent tests")
    conn = open_db_readonly()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def skip_if_raw_missing(table: PrimaryTable) -> None:
    """Skip when the in_path file is missing (gitignored CSVs in CI)."""
    if not table.payload_in_path.exists():
        pytest.skip(f"raw/cleaned file not on disk: {table.payload_in_path}")
