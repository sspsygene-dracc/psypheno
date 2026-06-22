"""Tests for `promote-dev-to-prod` (issue #178).

The command copies dev's already-built SQLite file(s) into prod and atomically
swaps them in — no rebuild, no restart. These tests drive the real LOCAL
transport against temp dirs standing in for the /hive trees (no SSH, no
network), so they exercise the actual cp/mv swap and the smoke-check guards.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from processing import deploy
from processing.deploy import (
    DeployError,
    _resolve_promote_local,
    run_promote_dev_to_prod,
)


def _make_db(path: Path, table: str, n_rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {table}(x)")
    conn.executemany(f"INSERT INTO {table} VALUES(?)", [(i,) for i in range(n_rows)])
    conn.commit()
    conn.close()


def _count(path: Path, table: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def hive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Point DEV_PATH/PROD_PATH at temp dirs and report key file paths."""
    dev = tmp_path / "sspsygene_website_dev"
    prod = tmp_path / "sspsygene_website"
    (dev / "data" / "db").mkdir(parents=True)
    (prod / "data" / "db").mkdir(parents=True)
    monkeypatch.setattr(deploy, "DEV_PATH", str(dev))
    monkeypatch.setattr(deploy, "PROD_PATH", str(prod))
    return {
        "dev_main": dev / "data/db/sspsygene.db",
        "dev_meta": dev / "data/db/sspsygene-meta.db",
        "prod_main": prod / "data/db/sspsygene.db",
        "prod_meta": prod / "data/db/sspsygene-meta.db",
        "prod_db_dir": prod / "data/db",
    }


def test_resolve_local_off_hive_raises() -> None:
    # On the test host the real /hive paths are absent, so auto-detect is SSH
    # (local=False) and an explicit --local must fail.
    assert _resolve_promote_local(None) is False
    with pytest.raises(DeployError, match="can't see the /hive trees"):
        _resolve_promote_local(True)


def test_resolve_auto_detects_local(hive: dict[str, Path]) -> None:
    # With DEV_PATH/PROD_PATH present as dirs, auto-detect picks local.
    assert _resolve_promote_local(None) is True
    assert _resolve_promote_local(True) is True
    assert _resolve_promote_local(False) is False


def test_promote_copies_both_dbs_and_swaps(hive: dict[str, Path]) -> None:
    _make_db(hive["dev_main"], "data_tables", 9)
    _make_db(hive["dev_meta"], "combined_pvalue_groups", 3)
    _make_db(hive["prod_main"], "data_tables", 2)  # stale prod
    _make_db(hive["prod_meta"], "combined_pvalue_groups", 1)
    inode_before = hive["prod_main"].stat().st_ino

    run_promote_dev_to_prod(local=True)

    assert _count(hive["prod_main"], "data_tables") == 9
    assert _count(hive["prod_meta"], "combined_pvalue_groups") == 3
    # Atomic swap → new inode (what the web app's inode-keyed reopen detects).
    assert hive["prod_main"].stat().st_ino != inode_before
    # No staging files left behind.
    assert not list(hive["prod_db_dir"].glob("*.new"))


def test_promote_main_only_when_no_meta_flag(hive: dict[str, Path]) -> None:
    _make_db(hive["dev_main"], "data_tables", 5)
    _make_db(hive["dev_meta"], "combined_pvalue_groups", 4)
    _make_db(hive["prod_meta"], "combined_pvalue_groups", 1)  # must be left alone

    run_promote_dev_to_prod(local=True, include_meta_analysis=False)

    assert _count(hive["prod_main"], "data_tables") == 5
    # --no-meta-analysis leaves prod's meta untouched.
    assert _count(hive["prod_meta"], "combined_pvalue_groups") == 1


def test_promote_skips_meta_when_dev_lacks_it(hive: dict[str, Path]) -> None:
    _make_db(hive["dev_main"], "data_tables", 6)
    # No dev meta DB; prod's stale meta is left untouched (warned, not failed).
    _make_db(hive["prod_meta"], "combined_pvalue_groups", 1)

    run_promote_dev_to_prod(local=True, include_meta_analysis=True)

    assert _count(hive["prod_main"], "data_tables") == 6
    assert _count(hive["prod_meta"], "combined_pvalue_groups") == 1


def test_promote_refuses_missing_source(hive: dict[str, Path]) -> None:
    with pytest.raises(DeployError, match="Source main DB not found"):
        run_promote_dev_to_prod(local=True)


def test_promote_refuses_below_smoke_threshold(hive: dict[str, Path]) -> None:
    _make_db(hive["dev_main"], "data_tables", 1)
    with pytest.raises(DeployError, match="smoke check failed"):
        run_promote_dev_to_prod(local=True, min_data_tables=5)


def test_promote_dry_run_writes_nothing(hive: dict[str, Path]) -> None:
    _make_db(hive["dev_main"], "data_tables", 9)
    _make_db(hive["dev_meta"], "combined_pvalue_groups", 3)
    _make_db(hive["prod_main"], "data_tables", 2)

    run_promote_dev_to_prod(local=True, dry_run=True)

    # Prod is unchanged and no staging file appeared.
    assert _count(hive["prod_main"], "data_tables") == 2
    assert not list(hive["prod_db_dir"].glob("*.new"))
