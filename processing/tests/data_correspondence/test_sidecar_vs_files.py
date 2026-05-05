"""Manifest counts vs. real on-disk files (#113).

Local-only — needs both the gitignored raw/cleaned CSVs (set
`SSPSYGENE_DATA_DIR` if running in a worktree) and the live SQLite
(`data/db/sspsygene.db`). Skips per-test when those aren't around.

Verifies that the row counts the manifest commits to actually match what's
on disk and in the DB:

  * raw_file row count == manifest.raw_rows
  * cleaned_file row count == manifest.cleaned_rows (Pipeline-built tables)
  * `SELECT COUNT(*) FROM <table>` == manifest.db_rows
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from .helpers import (
    PrimaryTable,
    manifest_entry_for,
    payload_dataset_dir,
)


def _read_csv_rows(dataset: str, filename: str, sep: str) -> int | None:
    """Pandas-based row count, mirroring `load_data_table`'s read_csv."""
    p = payload_dataset_dir(dataset) / filename
    if not p.exists():
        return None
    return len(pd.read_csv(p, sep=sep, dtype=str))


def test_raw_file_row_count(table: PrimaryTable) -> None:
    """The raw file's row count must match `manifest.raw_rows` (when both
    the file is on disk and the manifest commits to a count).
    """
    entry = manifest_entry_for(table)
    if entry is None:
        pytest.skip("manifest missing — covered by test_row_accounting")
    if "raw_rows" not in entry:
        pytest.skip(
            "manifest doesn't commit to raw_rows (multi-sheet xlsx or "
            "concat_and_write — file rowcount needs xlsx parsing)"
        )

    raw = _read_csv_rows(table.dataset, entry["raw_file"], table.separator)
    if raw is None:
        pytest.skip(f"raw file {entry['raw_file']} not on disk")

    assert raw == entry["raw_rows"], (
        f"{table.dataset}/{entry['raw_file']}: actual rowcount={raw}, "
        f"manifest.raw_rows={entry['raw_rows']}"
    )


def test_cleaned_file_row_count(table: PrimaryTable) -> None:
    """When the manifest tracks a `cleaned_file`, its row count must match."""
    entry = manifest_entry_for(table)
    if entry is None:
        pytest.skip("manifest missing")
    if "cleaned_file" not in entry or "cleaned_rows" not in entry:
        pytest.skip("no cleaned_file / cleaned_rows in manifest")

    cleaned = _read_csv_rows(table.dataset, entry["cleaned_file"], table.separator)
    if cleaned is None:
        pytest.skip(f"cleaned file {entry['cleaned_file']} not on disk")

    assert cleaned == entry["cleaned_rows"], (
        f"{table.dataset}/{entry['cleaned_file']}: actual rowcount={cleaned}, "
        f"manifest.cleaned_rows={entry['cleaned_rows']}"
    )


def test_db_row_count(table: PrimaryTable, db: sqlite3.Connection) -> None:
    """`SELECT COUNT(*) FROM <table>` must match `manifest.db_rows`."""
    entry = manifest_entry_for(table)
    if entry is None:
        pytest.skip("manifest missing")
    if "db_rows" not in entry:
        pytest.skip("manifest doesn't commit to db_rows (DB unavailable at gen time)")

    row = db.execute(
        f"SELECT COUNT(*) AS n FROM {table.table_name}"
    ).fetchone()
    assert row["n"] == entry["db_rows"], (
        f"{table.table_name}: SELECT COUNT(*) = {row['n']}, "
        f"manifest.db_rows = {entry['db_rows']}"
    )


def test_db_rows_equal_cleaned_rows(table: PrimaryTable, db: sqlite3.Connection) -> None:
    """End-to-end invariant: `cleaned_rows == db_rows` (load-db doesn't drop)."""
    entry = manifest_entry_for(table)
    if entry is None:
        pytest.skip("manifest missing")
    if "cleaned_rows" not in entry or "db_rows" not in entry:
        pytest.skip("manifest missing one side of cleaned_rows/db_rows")

    assert entry["cleaned_rows"] == entry["db_rows"], (
        f"{table.table_name}: cleaned_rows={entry['cleaned_rows']} but "
        f"db_rows={entry['db_rows']} — load-db doesn't drop rows, so this "
        "indicates either a manifest bug or a non-Pipeline transform we "
        "don't yet account for."
    )

    # Cross-check against the live DB to make sure nobody bumped one side
    # of the manifest without re-running load-db.
    row = db.execute(
        f"SELECT COUNT(*) AS n FROM {table.table_name}"
    ).fetchone()
    assert row["n"] == entry["db_rows"], (
        f"{table.table_name}: live DB has {row['n']} rows but "
        f"manifest.db_rows={entry['db_rows']} (rerun load-db or update manifest)"
    )
