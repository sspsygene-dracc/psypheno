"""Tests for `sspsygene rsync-dataset` (issue #203).

Network-free: exercises the gitignored-file selection, config.yaml in_path
parsing, and the argument-validation error paths that fire *before* any SSH /
rsync touches the network. The actual transfer (rsync over ssh to /hive) isn't
unit-tested — it needs a live server — but the file-list and validation logic
that decides *what* gets pushed is the part most likely to regress.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from processing.click.main import cli
from processing.rsync_dataset import (
    _config_in_paths,
    _gitignored_files,
    run_rsync_dataset,
)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def repo_with_dataset(tmp_path: Path) -> Path:
    """A throwaway git repo with one dataset dir: tracked config + ignored data.

    Mirrors the real layout — config.yaml / preprocess.py are tracked, the raw
    + cleaned data files are gitignored — so _gitignored_files sees exactly the
    payloads rsync-dataset should push.
    """
    repo = tmp_path / "repo"
    ds = repo / "data" / "datasets" / "foo"
    ds.mkdir(parents=True)
    (repo / ".gitignore").write_text("*.csv\n*.tsv\n")
    (ds / "config.yaml").write_text(
        "tables:\n  - table: foo_t\n    in_path: foo_cleaned.tsv\n"
    )
    (ds / "preprocess.py").write_text("# noop\n")
    (ds / "foo_raw.csv").write_text("a,b\n1,2\n")
    (ds / "foo_cleaned.tsv").write_text("a\tb\n1\t2\n")

    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)
    return repo


def test_gitignored_files_excludes_tracked(repo_with_dataset: Path) -> None:
    ds = repo_with_dataset / "data" / "datasets" / "foo"
    files = set(_gitignored_files(ds))
    # Only the gitignored data payloads — never the tracked config/preprocess.
    assert files == {"foo_raw.csv", "foo_cleaned.tsv"}
    assert "config.yaml" not in files
    assert "preprocess.py" not in files


def test_gitignored_files_empty_when_all_tracked(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    ds = repo / "data" / "datasets" / "bar"
    ds.mkdir(parents=True)
    (ds / "config.yaml").write_text("tables: []\n")
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)
    assert _gitignored_files(ds) == []


def test_config_in_paths_parses_in_path(repo_with_dataset: Path) -> None:
    ds = repo_with_dataset / "data" / "datasets" / "foo"
    assert _config_in_paths(ds) == ["foo_cleaned.tsv"]


def test_config_in_paths_no_config(tmp_path: Path) -> None:
    assert _config_in_paths(tmp_path) == []


def test_rsync_dataset_requires_a_name() -> None:
    with pytest.raises(Exception) as exc:
        run_rsync_dataset(datasets=(), instance="dev", host="hgwdev", dry_run=True)
    assert "at least one dataset" in str(exc.value)


def test_rsync_dataset_rejects_bad_instance(
    repo_with_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "SSPSYGENE_DATA_DIR", str(repo_with_dataset / "data")
    )
    monkeypatch.delenv("SSPSYGENE_CONFIG_JSON", raising=False)
    with pytest.raises(Exception) as exc:
        run_rsync_dataset(
            datasets=("foo",), instance="staging", host="hgwdev", dry_run=True
        )
    assert "--instance" in str(exc.value)


def test_rsync_dataset_unknown_dataset_errors(
    repo_with_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SSPSYGENE_DATA_DIR", str(repo_with_dataset / "data"))
    monkeypatch.delenv("SSPSYGENE_CONFIG_JSON", raising=False)
    with pytest.raises(Exception) as exc:
        run_rsync_dataset(
            datasets=("does-not-exist",),
            instance="dev",
            host="hgwdev",
            dry_run=True,
        )
    assert "does-not-exist" in str(exc.value)


def test_cli_rsync_dataset_requires_arg() -> None:
    """The Click command itself rejects a missing dataset name."""
    result = CliRunner().invoke(cli, ["rsync-dataset"])
    assert result.exit_code != 0
    assert "Missing argument" in result.output or "DATASETS" in result.output
