"""Test-wide pytest fixtures."""

import os
import pytest


@pytest.fixture(autouse=True)
def _isolate_r_cache(
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
