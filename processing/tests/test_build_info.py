"""Build-identity stamping shared by the main / meta / overview DBs (#225).

The properties that matter are all about *survival*: a build UUID has to
survive a promotion copy and a destination subset, because those are exactly
the operations the old (mtime, size) fingerprint could not survive.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from processing.build_info import (
    copy_build_info,
    read_build_uuid,
    write_build_info,
)


def _new_db(path: Path) -> sqlite3.Connection:
    # uri=True mirrors NewSqlite3, which is what makes the read-only
    # `file:...?mode=ro` ATTACH the subsetter relies on work.
    return sqlite3.connect(path, uri=True)


def test_write_build_info_stamps_a_uuid(tmp_path: Path) -> None:
    conn = _new_db(tmp_path / "main.db")
    build_uuid = write_build_info(conn)
    assert build_uuid
    assert read_build_uuid(conn) == build_uuid


def test_each_build_gets_a_distinct_uuid(tmp_path: Path) -> None:
    first = write_build_info(_new_db(tmp_path / "a.db"))
    second = write_build_info(_new_db(tmp_path / "b.db"))
    assert first != second


def test_read_build_uuid_is_none_for_a_pre_225_db(tmp_path: Path) -> None:
    """A DB built before build_info existed must read as 'unknown', not blow
    up — the web app treats unknown as not-stale rather than showing a banner."""
    conn = _new_db(tmp_path / "old.db")
    conn.execute("CREATE TABLE data_tables (table_name TEXT)")
    conn.commit()
    assert read_build_uuid(conn) is None


def test_uuid_survives_a_file_copy(tmp_path: Path) -> None:
    """The point of the change (#225): promotion copies DB files between
    instances, and `cp` gives the target a fresh mtime. A fingerprint based on
    the file's (mtime, size) marked every correctly-promoted meta DB stale; a
    UUID lives in the content, so it comes through unchanged."""
    src = tmp_path / "dev.db"
    build_uuid = write_build_info(_new_db(src))

    dst = tmp_path / "prod.db"
    shutil.copyfile(src, dst)
    dst.touch()  # what cp + the atomic mv swap do to mtime

    assert read_build_uuid(_new_db(dst)) == build_uuid
    assert dst.stat().st_mtime != src.stat().st_mtime


def test_copy_build_info_carries_the_uuid_across_a_subset(tmp_path: Path) -> None:
    """`subset-db` derives a destination DB from the superset. It is the same
    *build*, so it must keep the same UUID — otherwise the meta and overview
    DBs promoted alongside it would read as stale."""
    src = tmp_path / "dev.db"
    build_uuid = write_build_info(_new_db(src))

    subset = _new_db(tmp_path / "prod.db")
    subset.execute(f"ATTACH DATABASE 'file:{src}?mode=ro' AS src")
    carried = copy_build_info(subset, "src")
    subset.execute("DETACH DATABASE src")

    assert carried == build_uuid
    assert read_build_uuid(subset) == build_uuid


def test_copy_build_info_tolerates_a_source_without_build_info(
    tmp_path: Path,
) -> None:
    src = tmp_path / "old.db"
    old = _new_db(src)
    old.execute("CREATE TABLE data_tables (table_name TEXT)")
    old.commit()
    old.close()

    subset = _new_db(tmp_path / "out.db")
    subset.execute(f"ATTACH DATABASE 'file:{src}?mode=ro' AS src")
    assert copy_build_info(subset, "src") is None
    # The table exists but is empty — readable, just "unknown".
    assert read_build_uuid(subset) is None
