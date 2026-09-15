"""Tests for pull-data / push-data transfer progress bars.

Network-free: covers the pure decision logic (does this transfer warrant a
bar, and how big is it) plus the parsing of rsync's `--info=progress2` output,
which is the part that would silently stop updating if rsync ever changed its
format. The transfer itself needs a live server and isn't unit-tested.
"""

from __future__ import annotations

import subprocess

import pytest

from processing.pull_data import (
    PROGRESS_MIN_FILE_BYTES,
    _PROGRESS_RE,
    _progress_total,
    _rsync_supports_progress,
)

BIG = PROGRESS_MIN_FILE_BYTES
SMALL = 4096


def test_no_bar_when_every_file_is_small() -> None:
    """A pile of small files transfers faster than a bar would take to mean
    anything — the streamed filenames are the more useful output there."""
    sizes = {"a.csv": SMALL, "b.tsv": SMALL * 100}
    assert _progress_total(sizes, ["a.csv", "b.tsv"]) is None


def test_bar_when_one_file_crosses_the_threshold() -> None:
    """One big file is enough: it's the one that makes the transfer go quiet."""
    sizes = {"a.csv": SMALL, "huge.xlsx": BIG}
    assert _progress_total(sizes, ["a.csv", "huge.xlsx"]) == SMALL + BIG


def test_threshold_is_inclusive() -> None:
    assert _progress_total({"f": BIG}, ["f"]) == BIG
    assert _progress_total({"f": BIG - 1}, ["f"]) is None


def test_total_counts_only_files_that_will_transfer() -> None:
    """The caller passes the post-filter list (locally-missing files for a
    pull), so files already present must not inflate the bar."""
    sizes = {"already_here.tsv": BIG, "missing.tsv": BIG}
    assert _progress_total(sizes, ["missing.tsv"]) == BIG


def test_no_bar_for_an_empty_or_unknown_file_list() -> None:
    assert _progress_total({"a": BIG}, []) is None
    assert _progress_total({}, ["a"]) is None


@pytest.mark.parametrize(
    "line, expected",
    [
        ("     32,768   0%    0.00kB/s    0:00:00", 32_768),
        ("     60,000,000  99%  866.50MB/s    0:00:00 (xfr#1, to-chk=1/3)", 60_000_000),
        ("  1,048,576  3%    1.00MB/s    0:00:10", 1_048_576),
        # A transferred filename must never be mistaken for a progress chunk,
        # or it would be swallowed instead of listed.
        ("supp_table_3.xlsx", None),
        ("data/datasets/sfari/genes.csv", None),
        ("rsync: some warning", None),
        ("", None),
    ],
)
def test_progress_line_parsing(line: str, expected: int | None) -> None:
    match = _PROGRESS_RE.match(line)
    got = int(match.group(1).replace(",", "")) if match else None
    assert got == expected


def test_capability_probe_says_no_when_rsync_lacks_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """macOS ships openrsync, which has no --info at all; passing the flag
    there aborts the transfer, so we must detect it rather than assume."""
    _rsync_supports_progress.cache_clear()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "unknown option"),
    )
    assert _rsync_supports_progress() is False
    _rsync_supports_progress.cache_clear()


def test_capability_probe_survives_rsync_being_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rsync_supports_progress.cache_clear()

    def boom(*a: object, **k: object) -> None:
        raise FileNotFoundError("no rsync")

    monkeypatch.setattr(subprocess, "run", boom)
    assert _rsync_supports_progress() is False
    _rsync_supports_progress.cache_clear()
