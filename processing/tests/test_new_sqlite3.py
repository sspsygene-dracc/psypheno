"""Tests for processing.new_sqlite3.NewSqlite3."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from processing.new_sqlite3 import NewSqlite3


def _logger() -> logging.Logger:
    return logging.getLogger("test_new_sqlite3")


def test_pragmas_applied_inside_with_block(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    with NewSqlite3(db, _logger()) as wrapper:
        cur = wrapper.conn.cursor()
        assert cur.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        # synchronous=NORMAL → integer 1
        assert cur.execute("PRAGMA synchronous").fetchone()[0] == 1
        # cache_size in pages is signed; we set negative kibibytes (-100000)
        assert cur.execute("PRAGMA cache_size").fetchone()[0] == -100000
        # temp_store=MEMORY → integer 2
        assert cur.execute("PRAGMA temp_store").fetchone()[0] == 2


def test_commits_on_clean_exit(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    with NewSqlite3(db, _logger()) as wrapper:
        wrapper.cursor.execute("CREATE TABLE t (x INTEGER)")
        wrapper.cursor.execute("INSERT INTO t VALUES (1)")
        wrapper.cursor.execute("INSERT INTO t VALUES (2)")

    # Re-open and read in a fresh connection. If the commit was elided, the
    # rows would be gone.
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT x FROM t ORDER BY x").fetchall()
    finally:
        conn.close()
    assert rows == [(1,), (2,)]


def test_rolls_back_on_exception(tmp_path: Path) -> None:
    db = tmp_path / "test.db"

    # Create the table in its own (clean) transaction so we can reason about
    # the state of inserts after the exception.
    with NewSqlite3(db, _logger()) as wrapper:
        wrapper.cursor.execute("CREATE TABLE t (x INTEGER)")

    with pytest.raises(RuntimeError, match="boom"):
        with NewSqlite3(db, _logger()) as wrapper:
            wrapper.cursor.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT x FROM t").fetchall()
    finally:
        conn.close()
    assert rows == []
