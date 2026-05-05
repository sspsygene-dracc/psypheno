"""Tests for the R meta-analysis result cache."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch
import pytest

from processing.combined_pvalues import r_cache, r_runner
from processing.combined_pvalues.data import CollectedPvalues


R_AVAILABLE = shutil.which("Rscript") is not None


def _r_packages_available():
    if not R_AVAILABLE:
        return False
    try:
        result = subprocess.run(
            ["Rscript", "-e", "library(poolr); library(ACAT); library(harmonicmeanp)"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


R_PACKAGES_AVAILABLE = _r_packages_available()
requires_r = pytest.mark.skipif(
    not R_PACKAGES_AVAILABLE,
    reason="Rscript with poolr/ACAT/harmonicmeanp not available",
)


@pytest.fixture
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point SSPSYGENE_R_CACHE_DIR at a tmp dir for the duration of the test."""
    cache_path = tmp_path / "r-cache"
    monkeypatch.setenv("SSPSYGENE_R_CACHE_DIR", str(cache_path))
    return cache_path


def _make_pvalues(
    per_table_data: dict[int, dict[str, list[float]]],
) -> CollectedPvalues:
    """Build a CollectedPvalues from {gene_id: {table: [pvals]}}."""
    out = CollectedPvalues()
    for gid, tables in per_table_data.items():
        for tbl, pvals in tables.items():
            out.per_table[gid][tbl] = list(pvals)
            out.all_pvalues[gid].extend(pvals)
    return out


class TestComputeKey:
    def test_same_inputs_same_key(self, tmp_path: Path):
        """Identical CSV bytes + script bytes produce identical keys."""
        d1 = tmp_path / "a"
        d2 = tmp_path / "b"
        d1.mkdir()
        d2.mkdir()
        for d in (d1, d2):
            (d / "collapsed_pvalues.csv").write_text("gene_id,pvalue\n1,0.05\n")
            (d / "raw_pvalues.csv").write_text("gene_id,pvalue\n1,0.05\n")
        script = tmp_path / "script.R"
        script.write_text("# noop\n")
        assert r_cache.compute_key(d1, script) == r_cache.compute_key(d2, script)

    def test_different_csv_bytes_different_key(self, tmp_path: Path):
        """A subset of rows (the --test pattern) produces a different key."""
        full = tmp_path / "full"
        sub = tmp_path / "sub"
        full.mkdir()
        sub.mkdir()
        (full / "collapsed_pvalues.csv").write_text(
            "gene_id,pvalue\n1,0.05\n2,0.10\n3,0.20\n"
        )
        (sub / "collapsed_pvalues.csv").write_text("gene_id,pvalue\n1,0.05\n")
        for d in (full, sub):
            (d / "raw_pvalues.csv").write_text("gene_id,pvalue\n1,0.05\n")
        script = tmp_path / "script.R"
        script.write_text("# noop\n")
        assert r_cache.compute_key(full, script) != r_cache.compute_key(sub, script)

    def test_different_script_bytes_different_key(self, tmp_path: Path):
        """Editing the R script invalidates entries with otherwise-identical inputs."""
        d = tmp_path / "inputs"
        d.mkdir()
        (d / "collapsed_pvalues.csv").write_text("gene_id,pvalue\n1,0.05\n")
        (d / "raw_pvalues.csv").write_text("gene_id,pvalue\n1,0.05\n")
        s1 = tmp_path / "v1.R"
        s2 = tmp_path / "v2.R"
        s1.write_text("# logic v1\n")
        s2.write_text("# logic v2\n")
        assert r_cache.compute_key(d, s1) != r_cache.compute_key(d, s2)

    def test_no_collision_under_concatenation(self, tmp_path: Path):
        """Length-prefixed framing prevents (a, b) colliding with (a+b, '')."""
        d1 = tmp_path / "a"
        d2 = tmp_path / "b"
        d1.mkdir()
        d2.mkdir()
        (d1 / "collapsed_pvalues.csv").write_text("AB")
        (d1 / "raw_pvalues.csv").write_text("CD")
        (d2 / "collapsed_pvalues.csv").write_text("ABCD")
        (d2 / "raw_pvalues.csv").write_text("")
        script = tmp_path / "script.R"
        script.write_text("# noop\n")
        assert r_cache.compute_key(d1, script) != r_cache.compute_key(d2, script)


class TestComputeKeyFromPvalues:
    """Streaming key must match the disk-based key on the same data.

    Drift here would silently corrupt cache lookups (cache populated via
    one path, queried via the other). This contract is what lets the
    existing on-disk cache entries continue to resolve.
    """

    def test_matches_disk_key(self, tmp_path: Path):
        pvalues = _make_pvalues({
            1: {"tbl_a": [0.05, 0.1], "tbl_b": [0.001]},
            2: {"tbl_a": [0.5]},
            3: {"tbl_b": [1e-300, 1e-200, 1e-50]},
        })
        script = tmp_path / "script.R"
        script.write_text("# v1\n")

        d = tmp_path / "inputs"
        d.mkdir()
        r_runner.write_r_inputs(d, pvalues)

        assert (
            r_cache.compute_key_from_pvalues(pvalues, script)
            == r_cache.compute_key(d, script)
        )

    def test_collapsed_csv_bytes_match_on_disk(self, tmp_path: Path):
        pvalues = _make_pvalues({
            1: {"tbl_a": [0.05, 0.1]},
            2: {"tbl_b": [0.001, 0.002, 0.003]},
        })
        d = tmp_path / "inputs"
        d.mkdir()
        r_runner.write_r_inputs(d, pvalues)

        assert (
            r_cache.collapsed_csv_bytes(pvalues)
            == (d / "collapsed_pvalues.csv").read_bytes()
        )
        assert (
            r_cache.raw_csv_bytes(pvalues)
            == (d / "raw_pvalues.csv").read_bytes()
        )


class TestStoreAndLookup:
    def test_round_trip(self, isolated_cache: Path, tmp_path: Path):
        results = tmp_path / "results.csv"
        results.write_text(
            "gene_id,fisher_p,cauchy_p,hmp_p,fisher_fdr,cauchy_fdr,hmp_fdr\n"
            "1,0.01,0.02,0.03,0.10,0.10,0.10\n"
        )
        r_cache.store("deadbeef", results)
        hit = r_cache.lookup("deadbeef")
        assert hit is not None
        assert hit == isolated_cache / "deadbeef.csv"
        assert hit.read_text() == results.read_text()

    def test_miss_returns_none(self, isolated_cache: Path):
        assert r_cache.lookup("nope") is None

    def test_store_is_atomic(self, isolated_cache: Path, tmp_path: Path):
        """No `<key>.csv.tmp` should remain after a successful store."""
        results = tmp_path / "results.csv"
        results.write_text("gene_id,fisher_p\n1,0.01\n")
        r_cache.store("abc123", results)
        leftover = list(isolated_cache.glob("*.tmp"))
        assert leftover == []


@requires_r
class TestCallRCombineCaching:
    """End-to-end: second call returns same answer without invoking Rscript."""

    def _pvalues(self):
        return _make_pvalues(
            {
                1: {"tbl_a": [0.01, 0.02], "tbl_b": [0.03]},
                2: {"tbl_a": [0.10], "tbl_b": [0.20, 0.25]},
                3: {"tbl_a": [0.50]},
            }
        )

    def test_second_call_hits_cache(self, isolated_cache: Path):
        pvalues = self._pvalues()
        first = r_runner.call_r_combine(pvalues)
        assert first is not None
        # Confirm the cache file landed.
        cached = list(isolated_cache.glob("*.csv"))
        assert len(cached) == 1

        # Second call: assert subprocess.run was NOT invoked.
        with patch.object(r_runner.subprocess, "run") as mock_run:
            second = r_runner.call_r_combine(pvalues)
        assert mock_run.call_count == 0
        assert second == first

    def test_no_cache_flag_bypasses_cache(self, isolated_cache: Path):
        pvalues = self._pvalues()
        r_runner.call_r_combine(pvalues, use_cache=True)
        # First call populated the cache. With use_cache=False, subprocess
        # must run again.
        with patch.object(
            r_runner.subprocess, "run", wraps=r_runner.subprocess.run
        ) as mock_run:
            r_runner.call_r_combine(pvalues, use_cache=False)
        # subprocess.run is called by _ensure_r_packages too, but the key
        # invocation we care about is the rscript-on-the-script call. Just
        # assert it was called at least once (vs zero in the cached case).
        assert mock_run.call_count >= 1

    def test_test_mode_subset_does_not_collide(self, isolated_cache: Path):
        """Strict subset of genes -> different cache key -> no poisoning."""
        full = self._pvalues()
        subset = _make_pvalues({1: {"tbl_a": [0.01, 0.02], "tbl_b": [0.03]}})

        r_runner.call_r_combine(full)
        r_runner.call_r_combine(subset)

        # Two distinct cache entries.
        cached = sorted(isolated_cache.glob("*.csv"))
        assert len(cached) == 2
