"""Reuse an existing meta DB whose input fingerprint still matches.

See `fingerprint.py` for what the fingerprint covers. When it matches, the
existing meta DB is byte-for-byte what a rebuild would produce, so instead of
recomputing we copy it to the staging path, re-stamp its `source_build_uuid`
with the current dataset DB's build UUID, and atomically swap it back — the
same group-writable swap (`_checkpoint_and_swap`) a full build uses.
"""

from __future__ import annotations

import datetime
import json
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .fingerprint import describe_changes, fingerprint_digest


def read_meta_info(meta_db: Path) -> dict[str, str] | None:
    """`meta_analysis_info` of `meta_db` as a dict; None if absent/unreadable."""
    if not meta_db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True)
        try:
            return dict(
                conn.execute("SELECT key, value FROM meta_analysis_info").fetchall()
            )
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def reuse_decision(
    meta_db: Path,
    components: dict[str, Any] | None,
    schema_version: str,
) -> tuple[bool, str]:
    """(reusable, reason). `reason` explains a rebuild, for the log."""
    if components is None:
        return False, (
            "the dataset DB has no per-table meta input hashes (built by an "
            "older load-db, or a table lacks one)"
        )
    info = read_meta_info(meta_db)
    if info is None:
        return False, f"no readable meta DB at {meta_db}"
    if info.get("schema_version") != schema_version:
        return False, (
            f"meta DB schema version {info.get('schema_version')!r} != "
            f"{schema_version!r}"
        )
    stored = info.get("input_fingerprint")
    if not stored:
        return False, "the existing meta DB records no input fingerprint"
    if stored != fingerprint_digest(components):
        try:
            old = json.loads(info.get("input_fingerprint_detail") or "null")
        except ValueError:
            old = None
        changes = describe_changes(old, components) or ["fingerprint digest"]
        return False, "inputs changed: " + "; ".join(changes)
    return True, "inputs unchanged"


def restamp_meta_db(
    meta_db: Path,
    source_build_uuid: str | None,
    *,
    staging_path: Callable[[Path], Path],
    checkpoint_and_swap: Callable[[Path, Path], None],
) -> bool:
    """Point the existing meta DB at `source_build_uuid`.

    Returns False (nothing written) when it already records that UUID. Works on
    a copy and swaps it in atomically, so readers never see a half-updated file
    and the result is 0664 regardless of the caller's umask."""
    info = read_meta_info(meta_db) or {}
    if info.get("source_build_uuid") == source_build_uuid:
        return False  # already current (both None: nothing to stamp)
    staging = staging_path(meta_db)
    shutil.copyfile(meta_db, staging)
    conn = sqlite3.connect(staging)
    try:
        if source_build_uuid is None:
            conn.execute(
                "DELETE FROM meta_analysis_info WHERE key = 'source_build_uuid'"
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO meta_analysis_info (key, value) "
                "VALUES ('source_build_uuid', ?)",
                (source_build_uuid,),
            )
        conn.execute(
            "INSERT OR REPLACE INTO meta_analysis_info (key, value) "
            "VALUES ('restamped_at', ?)",
            (datetime.datetime.now(datetime.timezone.utc).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()
    checkpoint_and_swap(staging, meta_db)
    return True
