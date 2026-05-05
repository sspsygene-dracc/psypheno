"""Tests for the `sspsygene` Click CLI (load-db variants).

These exercise `processing.click.main:cli` via Click's CliRunner against
the same mini fixture used by the sq_load integration test. Coverage
focuses on argument plumbing, --dataset filtering, error handling, and
--skip-missing-datasets — not on the loader internals (those have their
own integration test).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from click.testing import CliRunner

from processing.click.main import cli


_FAST_FLAGS = ["--skip-meta-analysis", "--skip-gene-descriptions", "--no-index"]


def _out_db(mini_data_root: Path) -> Path:
    return mini_data_root / "db" / "mini.db"


def test_load_db_full_run(mini_fixture: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["load-db", *_FAST_FLAGS])
    assert result.exit_code == 0, result.output
    out_db = _out_db(mini_fixture)
    assert out_db.exists()

    # The expected dynamic table is present.
    conn = sqlite3.connect(out_db)
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM data_tables"
            ).fetchall()
        }
    finally:
        conn.close()
    assert names == {"mini_perturb_deg"}


def test_load_db_dataset_filter(mini_fixture: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["load-db", "--dataset", "mini_perturb", *_FAST_FLAGS]
    )
    assert result.exit_code == 0, result.output
    assert _out_db(mini_fixture).exists()

    conn = sqlite3.connect(_out_db(mini_fixture))
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM data_tables").fetchone()
    finally:
        conn.close()
    assert count == 1


def test_load_db_unknown_dataset_errors(mini_fixture: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["load-db", "--dataset", "does-not-exist", *_FAST_FLAGS]
    )
    assert result.exit_code != 0
    # The unknown-dataset path raises FileNotFoundError from
    # TablesConfig.from_yaml_root; Click captures it in `result.exception`.
    assert isinstance(result.exception, FileNotFoundError)
    assert "does-not-exist" in str(result.exception)


def test_load_db_skip_missing_datasets(mini_fixture: Path) -> None:
    """If `--skip-missing-datasets` is passed and a table's input file is
    missing, the run still succeeds and reports the table as skipped."""
    # Move the input file out of the way so the loader sees a missing in_path.
    in_path = mini_fixture / "datasets" / "mini_perturb" / "deg.tsv"
    moved = in_path.with_suffix(".tsv.hidden")
    in_path.rename(moved)
    try:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["load-db", "--skip-missing-datasets", *_FAST_FLAGS]
        )
        assert result.exit_code == 0, result.output
        assert "Skipped (missing)" in result.output
    finally:
        moved.rename(in_path)


def test_load_db_missing_input_without_skip_flag_errors(
    mini_fixture: Path,
) -> None:
    """Without `--skip-missing-datasets`, a missing in_path is fatal."""
    in_path = mini_fixture / "datasets" / "mini_perturb" / "deg.tsv"
    moved = in_path.with_suffix(".tsv.hidden")
    in_path.rename(moved)
    try:
        runner = CliRunner()
        result = runner.invoke(cli, ["load-db", *_FAST_FLAGS])
        assert result.exit_code == 1
        assert "File not found" in result.output
    finally:
        moved.rename(in_path)
