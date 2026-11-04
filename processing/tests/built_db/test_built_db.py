"""Quick sanity check of a built dataset DB (`scripts/test.sh db`).

Read-only. Runs against `$SSPSYGENE_DATA_DB`, else
`${SSPSYGENE_DATA_DIR:-<repo>/data}/db/sspsygene.db` (the same resolution as
`scripts/test.sh`). Kept out of the default unit run because it needs a built
DB; skips when the file is missing.

Checks:
- `central_gene` is non-empty;
- every `data_tables` row's table exists and has at least one row;
- every link table named in `data_tables.link_tables` exists and has at least
  one row.

All failures are collected and reported in a single assertion.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _db_path() -> Path:
    if os.environ.get("SSPSYGENE_DATA_DB"):
        return Path(os.environ["SSPSYGENE_DATA_DB"])
    data_dir = os.environ.get("SSPSYGENE_DATA_DIR") or str(REPO_ROOT / "data")
    return Path(data_dir) / "db" / "sspsygene.db"


def _link_table_names(spec: str | None) -> list[str]:
    """Table names from a `link_tables` spec.

    Format (written by sq_load): comma-separated `column:table:direction`
    entries. Parsed the same way the web app does (web/lib/gene-query.ts).
    """
    names = []
    for entry in (spec or "").split(","):
        parts = entry.strip().split(":")
        if len(parts) >= 2 and parts[1]:
            names.append(parts[1])
    return names


def _has_rows(conn: sqlite3.Connection, table: str) -> bool | None:
    """True/False for non-empty/empty; None if the table doesn't exist."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if not exists:
        return None
    quoted = '"' + table.replace('"', '""') + '"'
    return conn.execute(f"SELECT 1 FROM {quoted} LIMIT 1").fetchone() is not None


def test_built_db() -> None:
    path = _db_path()
    if not path.exists():
        pytest.skip(f"no built DB at {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        problems: list[str] = []

        def check(table: str, what: str) -> None:
            state = _has_rows(conn, table)
            if state is None:
                problems.append(f"{what} {table!r} is missing")
            elif not state:
                problems.append(f"{what} {table!r} is empty")

        check("central_gene", "table")
        rows = conn.execute(
            "SELECT table_name, link_tables FROM data_tables ORDER BY table_name"
        ).fetchall()
        if not rows:
            problems.append("data_tables has no rows")
        for table_name, link_spec in rows:
            check(table_name, "data table")
            for link in _link_table_names(link_spec):
                check(link, f"link table (of {table_name})")
    finally:
        conn.close()

    assert not problems, f"{len(problems)} problem(s) in {path}:\n" + "\n".join(
        f"  - {p}" for p in problems
    )
