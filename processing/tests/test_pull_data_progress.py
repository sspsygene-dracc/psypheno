"""Tests for pull-data / push-data transfer progress bars.

Network-free: covers the pure decision logic (does this transfer warrant a
bar, and how big is it), the parsing of rsync's `--progress` output, and the
aggregation that turns its per-file counter into one bar for a whole
operation. The transfer itself needs a live server and isn't unit-tested.
"""

from __future__ import annotations

import subprocess

import pytest

from processing.pull_data import (
    PROGRESS_MIN_FILE_BYTES,
    _PROGRESS_RE,
    _progress_total,
    _rsync_supports_progress,
    _TransferBar,
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
        ("     32768   0%    0.00kB/s    0:00:00", 32_768),
        ("    15728640 100%  311.85MB/s    0:00:00 (xfer#1, to-check=0/1)", 15_728_640),
        ("     1048576  20%  480.85kB/s    0:00:08", 1_048_576),
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


def test_bar_accumulates_across_files_rather_than_resetting() -> None:
    """`--progress` restarts its byte counter at every file, so the bar has to
    bank each finished file before the next one starts — otherwise a
    multi-file push would keep snapping back to near zero."""
    bar = _TransferBar(total=300, desc="test")
    bar._bar.disable = True

    bar.start_file()  # first file begins
    bar.note_bytes(50)
    bar.note_bytes(100)
    assert bar._bar.n == 100

    bar.start_file()  # second file begins; first file's 100 is banked
    bar.note_bytes(30)
    assert bar._bar.n == 130
    bar.note_bytes(200)
    assert bar._bar.n == 300


def test_bar_never_exceeds_its_total() -> None:
    """The total is an upper bound built from file sizes; a transfer that
    somehow reports more must not blow past 100%."""
    bar = _TransferBar(total=100, desc="test")
    bar._bar.disable = True
    bar.start_file()
    bar.note_bytes(10_000)
    assert bar._bar.n == 100


def test_bar_reads_as_done_when_closed() -> None:
    """rsync skips files already up to date, so a run can finish well short of
    its estimated total — it should still read as done, not stalled."""
    bar = _TransferBar(total=100, desc="test")
    bar._bar.disable = True
    bar.start_file()
    bar.note_bytes(10)
    bar.close()
    assert bar._bar.n == 100


def test_capability_probe_accepts_an_rsync_that_lists_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """macOS's stock openrsync has no `--info` at all but does have the
    classic `--progress` — probing for the latter is what keeps a Mac from
    silently losing its bar (#241)."""
    _rsync_supports_progress.cache_clear()
    help_text = "     --progress              show progress during transfer\n"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, help_text, ""),
    )
    assert _rsync_supports_progress() is True
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
