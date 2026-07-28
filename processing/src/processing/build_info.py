"""Build identity shared by the main, meta and overview DBs (#225).

Each `load-db` stamps a fresh UUID into the main DB's `build_info` table. The
meta and overview DBs record the `build_uuid` of the main DB they were computed
from, and the web app compares the two to decide whether a derived DB has
drifted from its source.

Why a UUID and not the source file's (mtime, size), which is what #176
originally used: that is a property of a *file*, and promotion copies files.
`cp` gives prod's main DB a fresh mtime, so a correctly-promoted meta DB read
as permanently stale on every instance it was copied to. A UUID travels with
the content — it survives the promotion copy, and `subset-db` deliberately
carries it across, so a subsetted prod main DB still matches the meta and
overview DBs copied beside it.

Advisory only: the staleness banner never blocks rendering, and a DB with no
`build_info` (predating #225) reads as "unknown freshness", not "stale".
"""

from __future__ import annotations

import datetime
import sqlite3
import uuid


def write_build_info(conn: sqlite3.Connection) -> str:
    """Create `build_info` in `conn`'s main schema and stamp a fresh UUID."""
    build_uuid = str(uuid.uuid4())
    rows = {
        "build_uuid": build_uuid,
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    conn.execute("CREATE TABLE build_info (key TEXT PRIMARY KEY, value TEXT)")
    conn.executemany(
        "INSERT INTO build_info (key, value) VALUES (?, ?)", list(rows.items())
    )
    conn.commit()
    return build_uuid


def copy_build_info(
    conn: sqlite3.Connection, src_schema: str = "src"
) -> str | None:
    """Copy `build_info` verbatim from an attached schema into `conn`'s main.

    Used by `subset-db`: a destination subset is the *same build* as the
    superset it came from, so it must keep the same UUID or the meta/overview
    DBs promoted alongside it would read as stale.
    """
    conn.execute("CREATE TABLE build_info (key TEXT PRIMARY KEY, value TEXT)")
    try:
        rows = conn.execute(
            f"SELECT key, value FROM {src_schema}.build_info"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    conn.executemany(
        "INSERT INTO build_info (key, value) VALUES (?, ?)", rows
    )
    conn.commit()
    return read_build_uuid(conn, "main")


def read_build_uuid(
    conn: sqlite3.Connection, schema: str = "main"
) -> str | None:
    """Read `build_info.build_uuid` from an attached schema.

    Returns None when the table is absent — a DB built before #225.
    """
    try:
        row = conn.execute(
            f"SELECT value FROM {schema}.build_info WHERE key = 'build_uuid'"
        ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None
