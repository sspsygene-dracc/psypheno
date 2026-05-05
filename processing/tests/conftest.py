"""Test-wide pytest fixtures."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture(autouse=True)
def _isolate_r_cache(  # type: ignore
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point SSPSYGENE_R_CACHE_DIR at a per-session tmp dir.

    Without this, tests that mock the R subprocess and let the real
    `r_cache.store` write into the developer's `processing/r-cache/`
    pollute that directory and cross-contaminate other tests.
    """
    if "SSPSYGENE_R_CACHE_DIR" not in os.environ:
        monkeypatch.setenv(
            "SSPSYGENE_R_CACHE_DIR",
            str(tmp_path_factory.mktemp("r-cache")),
        )


# Files the central_gene_table builder reads from data/homology/.
_REQUIRED_HOMOLOGY_FILES = (
    "hgnc_complete_set.txt",
    "MGI_EntrezGene.rpt",
    "HGNC_AllianceHomology.rpt",
)

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _resolve_real_homology_dir() -> Path:
    """Locate the real `data/homology/` directory.

    Order: (1) `$SSPSYGENE_TEST_HOMOLOGY_DIR`, (2) `<repo-root>/data/homology/`
    discovered by walking up from this file. Hard-fails if neither has the
    required files — a silent skip would mask the integration test.
    """
    env = os.environ.get("SSPSYGENE_TEST_HOMOLOGY_DIR")
    if env:
        candidate = Path(env)
        _check_homology_dir(candidate, source=f"$SSPSYGENE_TEST_HOMOLOGY_DIR ({env})")
        return candidate

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "homology"
        if all((candidate / name).exists() for name in _REQUIRED_HOMOLOGY_FILES):
            return candidate

    raise pytest.UsageError(
        "Could not find data/homology/. Set $SSPSYGENE_TEST_HOMOLOGY_DIR to "
        "an absolute path containing "
        f"{', '.join(_REQUIRED_HOMOLOGY_FILES)} (e.g. "
        "/Users/jbirgmei/prog/sspsygene/data/homology) before running tests "
        "from a worktree."
    )


def _check_homology_dir(path: Path, *, source: str) -> None:
    missing = [
        name for name in _REQUIRED_HOMOLOGY_FILES if not (path / name).exists()
    ]
    if missing:
        raise pytest.UsageError(
            f"Homology dir from {source} is missing required files: "
            f"{', '.join(missing)}"
        )


@pytest.fixture(scope="session")
def real_homology_dir() -> Path:
    """The real data/homology/ directory used by the integration tests."""
    return _resolve_real_homology_dir()


@pytest.fixture(scope="session")
def mini_data_root(
    tmp_path_factory: pytest.TempPathFactory, real_homology_dir: Path
) -> Path:
    """Session-scoped data root layout consumed by sq_load.

    Layout:
        <root>/homology/{hgnc_complete_set.txt,...}   # symlinks to real files
        <root>/datasets/globals.yaml                   # copy
        <root>/datasets/mini_perturb/                  # copy
        <root>/db/                                     # empty; sq_load writes here
        <root>/side-config.json                        # written from template

    Returns the root path. Tests get an `SSPSYGENE_DATA_DIR` env var pointing
    here via the per-test `mini_fixture`.
    """
    root = tmp_path_factory.mktemp("sspsygene-mini-data-root")
    homology_dir = root / "homology"
    homology_dir.mkdir()
    for name in _REQUIRED_HOMOLOGY_FILES:
        (homology_dir / name).symlink_to(real_homology_dir / name)

    datasets_dir = root / "datasets"
    datasets_dir.mkdir()
    fixture_root = _FIXTURES_DIR / "mini-dataset"
    shutil.copy2(fixture_root / "globals.yaml", datasets_dir / "globals.yaml")
    shutil.copytree(
        fixture_root / "mini_perturb", datasets_dir / "mini_perturb"
    )

    (root / "db").mkdir()

    # Write a side config from the template (paths in the template are
    # already relative to SSPSYGENE_DATA_DIR, so no substitution is needed).
    template = json.loads(
        (_FIXTURES_DIR / "side-config-template.json").read_text()
    )
    (root / "side-config.json").write_text(json.dumps(template, indent=2))

    return root


def _reset_module_caches() -> None:
    """Clear caches that close over `SSPSYGENE_DATA_DIR` / `SSPSYGENE_CONFIG_JSON`."""
    from processing import config as _config
    import processing.central_gene_table as _cgt

    _config.get_sspsygene_config.cache_clear()
    _cgt._CENTRAL_GENE_TABLE = None


@pytest.fixture
def mini_fixture(
    monkeypatch: pytest.MonkeyPatch, mini_data_root: Path
) -> Iterator[Path]:
    """Per-test fixture that points env vars at the session mini data root.

    Clears `get_sspsygene_config`'s lru_cache and the
    `central_gene_table._CENTRAL_GENE_TABLE` module global before and after
    the test so each test sees a fresh build keyed off the env vars.

    Yields the data root path (the parent of `db/`, `homology/`, `datasets/`).
    """
    monkeypatch.setenv("SSPSYGENE_DATA_DIR", str(mini_data_root))
    monkeypatch.setenv(
        "SSPSYGENE_CONFIG_JSON", str(mini_data_root / "side-config.json")
    )

    # The session-scoped mini_data_root is reused across tests — wipe any
    # built DBs from prior tests so each invocation starts from an empty db/.
    db_dir = mini_data_root / "db"
    for entry in db_dir.iterdir():
        entry.unlink()

    _reset_module_caches()
    try:
        yield mini_data_root
    finally:
        _reset_module_caches()
