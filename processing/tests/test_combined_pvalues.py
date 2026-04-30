"""Tests for the combined p-value pipeline.

Covers: _precollapse, _parse_link_tables_for_direction, _load_hgnc_gene_flags,
_filter_collected, _write_r_inputs / _parse_r_results, ComputeGroupBuilder,
GeneFlagger, _call_r_combine, and compute_combined_pvalues.
"""

# pylint: disable=use-implicit-booleaness-not-comparison

import csv
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from processing.combined_pvalues import (
    CollectedPvalues,
    ComputeGroupBuilder,
    GeneCombinedPvalues,
    GeneFlagger,
    _call_r_combine,  # pyright: ignore[reportPrivateUsage]
    _filter_collected,  # pyright: ignore[reportPrivateUsage]
    _load_hgnc_gene_flags,  # pyright: ignore[reportPrivateUsage]
    _parse_link_tables_for_direction,  # pyright: ignore[reportPrivateUsage]
    _parse_r_results,  # pyright: ignore[reportPrivateUsage]
    _precollapse,  # pyright: ignore[reportPrivateUsage]
    _write_r_inputs,  # pyright: ignore[reportPrivateUsage]
    compute_combined_pvalues,
)

# ---------------------------------------------------------------------------
# R availability check
# ---------------------------------------------------------------------------

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
        )
        return result.returncode == 0
    except Exception:
        return False


R_PACKAGES_AVAILABLE = _r_packages_available()

requires_r = pytest.mark.skipif(
    not R_PACKAGES_AVAILABLE,
    reason="Rscript with poolr/ACAT/harmonicmeanp not available",
)


# ===================================================================
# 1. TestPrecollapse — pure math, no I/O
# ===================================================================


class TestPrecollapse:
    def test_single_pvalue_returns_itself(self):
        assert _precollapse([0.05]) == pytest.approx(0.05)

    def test_multiple_pvalues_min_times_n(self):
        # min(0.1) * 3 = 0.3
        assert _precollapse([0.1, 0.2, 0.3]) == pytest.approx(0.3)

    def test_cap_at_one_when_exceeds(self):
        # min(0.6) * 2 = 1.2 -> capped at 1.0
        assert _precollapse([0.6, 0.7]) == 1.0

    def test_exactly_one(self):
        # min(0.5) * 2 = 1.0 exactly
        assert _precollapse([0.5, 0.5]) == 1.0

    def test_all_ones(self):
        # min(1.0) * 3 = 3.0 -> capped at 1.0
        assert _precollapse([1.0, 1.0, 1.0]) == 1.0

    def test_very_small_pvalue_precision(self):
        # min(1e-300) * 2 = 2e-300, mpmath keeps precision
        result = _precollapse([1e-300, 1e-280])
        assert result == pytest.approx(2e-300, rel=1e-10)

    def test_subnormal_float(self):
        # 5e-324 is the smallest positive float; 5e-324 * 2 = 1e-323
        result = _precollapse([5e-324, 1e-310])
        assert result == pytest.approx(5e-324 * 2, rel=1e-5)
        assert result > 0

    def test_returns_python_float(self):
        result = _precollapse([0.01, 0.02])
        assert isinstance(result, float)

    def test_many_identical_small_values(self):
        # 1e-200 * 100 = 1e-198
        result = _precollapse([1e-200] * 100)
        assert result == pytest.approx(1e-198, rel=1e-10)

    @pytest.mark.parametrize(
        "pvalues, expected",
        [
            ([0.05], 0.05),
            ([0.1, 0.2, 0.3], 0.3),
            ([0.5, 0.6], 1.0),
            ([0.001, 0.01, 0.1, 0.5], 0.004),
            ([1e-300, 1e-280], 2e-300),
            ([0.01, 0.99], 0.02),
        ],
    )
    def test_parametrized_known_values(self, pvalues: list[float], expected: float):
        result = _precollapse(pvalues)
        assert result == pytest.approx(expected, rel=1e-10)


# ===================================================================
# 2. TestParseLinkTables — pure string parsing
# ===================================================================


class TestParseLinkTablesForDirection:
    def test_empty_string(self):
        assert _parse_link_tables_for_direction("", "target") == []
        assert _parse_link_tables_for_direction("", "perturbed") == []

    def test_target_entry_kept_for_target(self):
        assert _parse_link_tables_for_direction("gene:tbl__link:target", "target") == [
            "tbl__link"
        ]

    def test_target_entry_dropped_for_perturbed(self):
        assert _parse_link_tables_for_direction("gene:tbl__link:target", "perturbed") == []

    def test_perturbed_entry_kept_for_perturbed(self):
        assert _parse_link_tables_for_direction("gene:tbl__pert:perturbed", "perturbed") == [
            "tbl__pert"
        ]

    def test_paired_table_splits_by_direction(self):
        raw = "gene:tbl__target:target,pert:tbl__pert:perturbed"
        assert _parse_link_tables_for_direction(raw, "target") == ["tbl__target"]
        assert _parse_link_tables_for_direction(raw, "perturbed") == ["tbl__pert"]

    def test_multiple_target(self):
        raw = "g1:lt1:target,g2:lt2:target"
        assert _parse_link_tables_for_direction(raw, "target") == ["lt1", "lt2"]
        assert _parse_link_tables_for_direction(raw, "perturbed") == []

    def test_whitespace_trimmed(self):
        raw = " gene:tbl__target:target , pert:tbl__pert:perturbed "
        assert _parse_link_tables_for_direction(raw, "target") == ["tbl__target"]

    def test_short_parts_skipped(self):
        # Fewer than 3 parts: entry is malformed and dropped.
        assert _parse_link_tables_for_direction("gene:tbl", "target") == []

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError):
            _parse_link_tables_for_direction("gene:tbl:target", "global")


# ===================================================================
# 3. TestLoadHgncGeneFlags — TSV file parsing
# ===================================================================


def _write_hgnc_tsv(path: Path, rows: list[dict[str, str]]):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["symbol", "gene_group", "locus_group"], delimiter="\t"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "symbol": row.get("symbol", ""),
                    "gene_group": row.get("gene_group", ""),
                    "locus_group": row.get("locus_group", ""),
                }
            )


class TestLoadHgncGeneFlags:
    def test_heat_shock_gene(self, tmp_path: Path):
        tsv = tmp_path / "hgnc.tsv"
        _write_hgnc_tsv(
            tsv,
            [{"symbol": "HSPA1A", "gene_group": "DNAJ (HSP40) heat shock proteins"}],
        )
        result = _load_hgnc_gene_flags(tsv)
        assert result == {"HSPA1A": "heat_shock"}

    def test_ribosomal_gene(self, tmp_path: Path):
        tsv = tmp_path / "hgnc.tsv"
        _write_hgnc_tsv(tsv, [{"symbol": "RPL5", "gene_group": "L ribosomal proteins"}])
        result = _load_hgnc_gene_flags(tsv)
        assert result == {"RPL5": "ribosomal"}

    def test_non_coding_locus_group(self, tmp_path: Path):
        tsv = tmp_path / "hgnc.tsv"
        _write_hgnc_tsv(tsv, [{"symbol": "MIR21", "locus_group": "non-coding RNA"}])
        result = _load_hgnc_gene_flags(tsv)
        assert result == {"MIR21": "non_coding"}

    def test_pseudogene_locus_group(self, tmp_path: Path):
        tsv = tmp_path / "hgnc.tsv"
        _write_hgnc_tsv(tsv, [{"symbol": "FAKEP1", "locus_group": "pseudogene"}])
        result = _load_hgnc_gene_flags(tsv)
        assert result == {"FAKEP1": "pseudogene"}

    def test_multiple_flags_sorted(self, tmp_path: Path):
        tsv = tmp_path / "hgnc.tsv"
        _write_hgnc_tsv(
            tsv,
            [
                {
                    "symbol": "GENE1",
                    "gene_group": "L ribosomal proteins",
                    "locus_group": "non-coding RNA",
                }
            ],
        )
        result = _load_hgnc_gene_flags(tsv)
        assert result == {"GENE1": "non_coding,ribosomal"}

    def test_pipe_separated_gene_groups(self, tmp_path: Path):
        tsv = tmp_path / "hgnc.tsv"
        _write_hgnc_tsv(
            tsv,
            [
                {
                    "symbol": "HSP90AA1",
                    "gene_group": '"Some other group"|"Heat shock 90kDa proteins"',
                }
            ],
        )
        result = _load_hgnc_gene_flags(tsv)
        assert result == {"HSP90AA1": "heat_shock"}

    def test_no_matching_flags_omitted(self, tmp_path: Path):
        tsv = tmp_path / "hgnc.tsv"
        _write_hgnc_tsv(
            tsv,
            [
                {
                    "symbol": "BRCA1",
                    "gene_group": "Other group",
                    "locus_group": "protein-coding gene",
                }
            ],
        )
        result = _load_hgnc_gene_flags(tsv)
        assert result == {}


# ===================================================================
# 4. TestCallRCombine — mocked subprocess
# ===================================================================


class TestCallRCombine:
    def test_rscript_not_found_returns_none(self):
        with patch("shutil.which", return_value=None):
            result = _call_r_combine(
                CollectedPvalues.from_dicts({1: {"t": [0.01]}}, {1: [0.01]})
            )
        assert result is None

    def test_parse_valid_results(self, tmp_path: Path):
        """Mock R to write a known results.csv, verify parsing."""
        per_table = {1: {"tbl_a": [0.01]}}
        all_pvals = {1: [0.01]}

        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            # The R script call has the temp dir as last arg
            if len(cmd) >= 3 and "compute_combined" in str(cmd[1]):
                tmp_dir = cmd[2]
                results_path = Path(tmp_dir) / "results.csv"
                with open(results_path, "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(
                        [
                            "gene_id",
                            "fisher_p",
                            "stouffer_p",
                            "cauchy_p",
                            "hmp_p",
                            "fisher_fdr",
                            "stouffer_fdr",
                            "cauchy_fdr",
                            "hmp_fdr",
                        ]
                    )
                    w.writerow(
                        [
                            "1",
                            "1.00000000000000000e-03",
                            "2.00000000000000000e-03",
                            "3.00000000000000000e-03",
                            "4.00000000000000000e-03",
                            "5.00000000000000000e-03",
                            "6.00000000000000000e-03",
                            "7.00000000000000000e-03",
                            "8.00000000000000000e-03",
                        ]
                    )
                return MagicMock(returncode=0, stdout="", stderr="")
            # The package-check call
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("shutil.which", return_value="/usr/bin/Rscript"),
            patch("processing.combined_pvalues.r_runner._ensure_r_packages", return_value=True),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = _call_r_combine(CollectedPvalues.from_dicts(per_table, all_pvals))

        assert result is not None
        assert result[1].fisher_p == pytest.approx(1e-3)
        assert result[1].stouffer_p == pytest.approx(2e-3)
        assert result[1].cauchy_p == pytest.approx(3e-3)
        assert result[1].hmp_p == pytest.approx(4e-3)
        assert result[1].fisher_fdr == pytest.approx(5e-3)

    def test_parse_na_nan_inf(self, tmp_path: Path):
        """NA, NaN, Inf, -Inf in R output → None in Python."""
        per_table = {1: {"t": [0.01]}}
        all_pvals = {1: [0.01]}

        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if len(cmd) >= 3 and "compute_combined" in str(cmd[1]):
                tmp_dir = cmd[2]
                results_path = Path(tmp_dir) / "results.csv"
                with open(results_path, "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(
                        [
                            "gene_id",
                            "fisher_p",
                            "stouffer_p",
                            "cauchy_p",
                            "hmp_p",
                            "fisher_fdr",
                            "stouffer_fdr",
                            "cauchy_fdr",
                            "hmp_fdr",
                        ]
                    )
                    w.writerow(
                        [
                            "1",
                            "NA",
                            "NaN",
                            "Inf",
                            "-Inf",
                            "1.00000000000000000e-02",
                            "",
                            "NA",
                            "NaN",
                        ]
                    )
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("shutil.which", return_value="/usr/bin/Rscript"),
            patch("processing.combined_pvalues.r_runner._ensure_r_packages", return_value=True),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = _call_r_combine(CollectedPvalues.from_dicts(per_table, all_pvals))

        assert result is not None
        assert result[1].fisher_p is None  # NA
        assert result[1].stouffer_p is None  # NaN
        assert result[1].cauchy_p is None  # Inf
        assert result[1].hmp_p is None  # -Inf
        assert result[1].fisher_fdr == pytest.approx(0.01)
        assert result[1].stouffer_fdr is None  # empty string
        assert result[1].cauchy_fdr is None  # NA
        assert result[1].hmp_fdr is None  # NaN

    def test_precision_roundtrip(self):
        """Verify .17e format preserves extreme values through CSV writing."""
        val = 1.23456789012345678e-200
        formatted = f"{val:.17e}"
        recovered = float(formatted)
        # IEEE 754 double has ~15-17 significant digits
        assert recovered == pytest.approx(val, rel=1e-15)


# ===================================================================
# 5. TestPvalueCollection — in-memory SQLite + mocked R
# ===================================================================


def _make_test_db():
    """Create in-memory SQLite with the schema compute_combined_pvalues expects."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE data_tables (
            table_name TEXT, short_label TEXT, long_label TEXT, description TEXT,
            gene_columns TEXT, gene_species TEXT, display_columns TEXT,
            scalar_columns TEXT, link_tables TEXT, links TEXT, categories TEXT,
            source TEXT, assay TEXT, field_labels TEXT, organism TEXT,
            organism_key TEXT,
            publication_title TEXT, publication_authors TEXT, publication_year TEXT,
            publication_doi TEXT, publication_url TEXT, publication_journal TEXT,
            pvalue_column TEXT, fdr_column TEXT, disease TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE central_gene (
            id INTEGER PRIMARY KEY, human_symbol TEXT, hgnc_id TEXT,
            mouse_symbols TEXT, mouse_mgi_accession_ids TEXT,
            mouse_ensembl_genes TEXT, human_synonyms TEXT, mouse_synonyms TEXT,
            dataset_names TEXT, num_datasets INTEGER, manually_added INTEGER,
            human_entrez_gene TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO central_gene (id, human_symbol, hgnc_id) VALUES (1, 'BRCA1', 'HGNC:1100')"
    )
    conn.execute(
        "INSERT INTO central_gene (id, human_symbol, hgnc_id) VALUES (2, 'TP53', 'HGNC:11998')"
    )
    conn.execute(
        "INSERT INTO central_gene (id, human_symbol, hgnc_id) VALUES (3, 'MYGENE', NULL)"
    )
    conn.commit()
    return conn


class TestPvalueCollection:
    def test_basic_collection(self):
        """1 table, 3 rows for gene 1 → 3 p-values collected."""
        conn = _make_test_db()
        conn.execute("CREATE TABLE tbl_a (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_a VALUES (1, 0.01)")
        conn.execute("INSERT INTO tbl_a VALUES (2, 0.05)")
        conn.execute("INSERT INTO tbl_a VALUES (3, 0.10)")
        conn.execute("CREATE TABLE tbl_a__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__link VALUES (1, 1)")
        conn.execute("INSERT INTO tbl_a__link VALUES (2, 1)")
        conn.execute("INSERT INTO tbl_a__link VALUES (3, 1)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_a', 'pval', 'gene:tbl_a__link:target')"
        )
        conn.commit()

        captured = {}

        def mock_r(pvalues: CollectedPvalues) -> dict[int, GeneCombinedPvalues]:
            per_table = pvalues.per_table
            all_pvals = pvalues.all_pvalues
            captured["per_table"] = {k: dict(v) for k, v in per_table.items()}
            captured["all_pvals"] = dict(all_pvals)
            return {}

        with patch("processing.combined_pvalues.r_runner._call_r_combine", side_effect=mock_r):
            compute_combined_pvalues(conn)

        assert sorted(captured["per_table"][1]["tbl_a"]) == pytest.approx(
            [0.01, 0.05, 0.10]
        )
        assert sorted(captured["all_pvals"][1]) == pytest.approx([0.01, 0.05, 0.10])

    def test_null_pvalues_excluded(self):
        conn = _make_test_db()
        conn.execute("CREATE TABLE tbl_a (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_a VALUES (1, 0.01)")
        conn.execute("INSERT INTO tbl_a VALUES (2, NULL)")
        conn.execute("CREATE TABLE tbl_a__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__link VALUES (1, 1)")
        conn.execute("INSERT INTO tbl_a__link VALUES (2, 1)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_a', 'pval', 'gene:tbl_a__link:target')"
        )
        conn.commit()

        captured = {}

        def mock_r(pvalues: CollectedPvalues) -> dict[int, GeneCombinedPvalues]:
            all_pvals = pvalues.all_pvalues
            captured["all_pvals"] = dict(all_pvals)
            return {}

        with patch("processing.combined_pvalues.r_runner._call_r_combine", side_effect=mock_r):
            compute_combined_pvalues(conn)

        assert captured["all_pvals"][1] == [0.01]

    def test_zero_pvalue_excluded(self):
        conn = _make_test_db()
        conn.execute("CREATE TABLE tbl_a (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_a VALUES (1, 0.0)")
        conn.execute("INSERT INTO tbl_a VALUES (2, 0.05)")
        conn.execute("CREATE TABLE tbl_a__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__link VALUES (1, 1)")
        conn.execute("INSERT INTO tbl_a__link VALUES (2, 1)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_a', 'pval', 'gene:tbl_a__link:target')"
        )
        conn.commit()

        captured = {}

        def mock_r(pvalues: CollectedPvalues) -> dict[int, GeneCombinedPvalues]:
            all_pvals = pvalues.all_pvalues
            captured["all_pvals"] = dict(all_pvals)
            return {}

        with patch("processing.combined_pvalues.r_runner._call_r_combine", side_effect=mock_r):
            compute_combined_pvalues(conn)

        assert captured["all_pvals"][1] == [0.05]

    def test_pvalue_above_one_excluded(self):
        conn = _make_test_db()
        conn.execute("CREATE TABLE tbl_a (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_a VALUES (1, 1.5)")
        conn.execute("INSERT INTO tbl_a VALUES (2, 0.05)")
        conn.execute("CREATE TABLE tbl_a__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__link VALUES (1, 1)")
        conn.execute("INSERT INTO tbl_a__link VALUES (2, 1)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_a', 'pval', 'gene:tbl_a__link:target')"
        )
        conn.commit()

        captured = {}

        def mock_r(pvalues: CollectedPvalues) -> dict[int, GeneCombinedPvalues]:
            all_pvals = pvalues.all_pvalues
            captured["all_pvals"] = dict(all_pvals)
            return {}

        with patch("processing.combined_pvalues.r_runner._call_r_combine", side_effect=mock_r):
            compute_combined_pvalues(conn)

        assert captured["all_pvals"][1] == [0.05]

    def test_pvalue_exactly_one_included(self):
        conn = _make_test_db()
        conn.execute("CREATE TABLE tbl_a (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_a VALUES (1, 1.0)")
        conn.execute("INSERT INTO tbl_a VALUES (2, 0.05)")
        conn.execute("CREATE TABLE tbl_a__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__link VALUES (1, 1)")
        conn.execute("INSERT INTO tbl_a__link VALUES (2, 1)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_a', 'pval', 'gene:tbl_a__link:target')"
        )
        conn.commit()

        captured = {}

        def mock_r(pvalues: CollectedPvalues) -> dict[int, GeneCombinedPvalues]:
            all_pvals = pvalues.all_pvalues
            captured["all_pvals"] = dict(all_pvals)
            return {}

        with patch("processing.combined_pvalues.r_runner._call_r_combine", side_effect=mock_r):
            compute_combined_pvalues(conn)

        assert sorted(captured["all_pvals"][1]) == pytest.approx([0.05, 1.0])

    def test_multiple_tables_separate_buckets(self):
        conn = _make_test_db()
        # Table A
        conn.execute("CREATE TABLE tbl_a (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_a VALUES (1, 0.01)")
        conn.execute("CREATE TABLE tbl_a__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__link VALUES (1, 1)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_a', 'pval', 'gene:tbl_a__link:target')"
        )
        # Table B
        conn.execute("CREATE TABLE tbl_b (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_b VALUES (1, 0.05)")
        conn.execute("CREATE TABLE tbl_b__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_b__link VALUES (1, 1)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_b', 'pval', 'gene:tbl_b__link:target')"
        )
        conn.commit()

        captured = {}

        def mock_r(pvalues: CollectedPvalues) -> dict[int, GeneCombinedPvalues]:
            per_table = pvalues.per_table
            captured["per_table"] = {k: dict(v) for k, v in per_table.items()}
            return {}

        with patch("processing.combined_pvalues.r_runner._call_r_combine", side_effect=mock_r):
            compute_combined_pvalues(conn)

        assert "tbl_a" in captured["per_table"][1]
        assert "tbl_b" in captured["per_table"][1]
        assert captured["per_table"][1]["tbl_a"] == [0.01]
        assert captured["per_table"][1]["tbl_b"] == [0.05]

    def test_multiple_pvalue_columns_same_bucket(self):
        """BUG PROBE: When a table has pvalue_column='pval_a,pval_b',
        both columns' p-values land in the same table_name bucket.
        A gene with 3 rows gets n=6 in precollapse (3 rows * 2 columns)
        instead of being treated as 2 separate signals."""
        conn = _make_test_db()
        conn.execute("CREATE TABLE tbl_multi (id INTEGER, pval_a REAL, pval_b REAL)")
        conn.execute("INSERT INTO tbl_multi VALUES (1, 0.01, 0.02)")
        conn.execute("INSERT INTO tbl_multi VALUES (2, 0.03, 0.04)")
        conn.execute("INSERT INTO tbl_multi VALUES (3, 0.05, 0.06)")
        conn.execute(
            "CREATE TABLE tbl_multi__link (id INTEGER, central_gene_id INTEGER)"
        )
        conn.execute("INSERT INTO tbl_multi__link VALUES (1, 1)")
        conn.execute("INSERT INTO tbl_multi__link VALUES (2, 1)")
        conn.execute("INSERT INTO tbl_multi__link VALUES (3, 1)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_multi', 'pval_a,pval_b', 'gene:tbl_multi__link:target')"
        )
        conn.commit()

        captured = {}

        def mock_r(pvalues: CollectedPvalues) -> dict[int, GeneCombinedPvalues]:
            per_table = pvalues.per_table
            all_pvals = pvalues.all_pvalues
            captured["per_table"] = {k: dict(v) for k, v in per_table.items()}
            captured["all_pvals"] = dict(all_pvals)
            return {}

        with patch("processing.combined_pvalues.r_runner._call_r_combine", side_effect=mock_r):
            compute_combined_pvalues(conn)

        # Both columns merge into same table key: 6 values total
        bucket = captured["per_table"][1]["tbl_multi"]
        assert len(bucket) == 6
        assert sorted(bucket) == pytest.approx([0.01, 0.02, 0.03, 0.04, 0.05, 0.06])

        # Pre-collapse with n=6: min(0.01) * 6 = 0.06
        collapsed = _precollapse(bucket)
        assert collapsed == pytest.approx(0.06, rel=1e-10)

    def test_perturbed_link_table_filtered(self):
        """When both perturbed and non-perturbed link tables exist,
        only non-perturbed is used for p-value collection."""
        conn = _make_test_db()
        conn.execute("CREATE TABLE tbl_a (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_a VALUES (1, 0.01)")
        conn.execute("INSERT INTO tbl_a VALUES (2, 0.05)")
        # Target link: row 1 → gene 1
        conn.execute("CREATE TABLE tbl_a__target (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__target VALUES (1, 1)")
        # Perturbed link: row 2 → gene 2
        conn.execute("CREATE TABLE tbl_a__pert (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__pert VALUES (2, 2)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_a', 'pval', 'target_gene:tbl_a__target:target,perturbed_gene:tbl_a__pert:perturbed')"
        )
        conn.commit()

        captures: list[dict[int, list[float]]] = []

        def mock_r(pvalues: CollectedPvalues) -> dict[int, GeneCombinedPvalues]:
            captures.append(dict(pvalues.all_pvalues))
            return {}

        with patch("processing.combined_pvalues.r_runner._call_r_combine", side_effect=mock_r):
            compute_combined_pvalues(conn)

        # The legacy "global" group filters perturbed when both sides exist:
        # gene 1 is collected via the target link, gene 2 is filtered out.
        global_call = captures[0]
        assert 1 in global_call
        assert global_call[1] == [0.01]
        assert 2 not in global_call


# ===================================================================
# 6. TestIntegrationWithR — requires R + packages
# ===================================================================


class TestIntegrationWithR:
    @requires_r
    def test_known_pvalues_fisher_stouffer(self):
        """Fisher and Stouffer on [0.01, 0.05, 0.1] (3 separate tables)."""
        per_table = {
            1: {"tbl_a": [0.01], "tbl_b": [0.05], "tbl_c": [0.1]},
        }
        all_pvals = {1: [0.01, 0.05, 0.1]}
        result = _call_r_combine(CollectedPvalues.from_dicts(per_table, all_pvals))
        assert result is not None
        assert result[1].fisher_p == pytest.approx(2.99715102020775949e-03, rel=1e-6)
        assert result[1].stouffer_p == pytest.approx(1.21196887876184683e-03, rel=1e-6)

    @requires_r
    def test_known_pvalues_cct_hmp(self):
        """CCT and HMP on [0.01, 0.05, 0.1] raw p-values."""
        per_table = {
            1: {"tbl_a": [0.01], "tbl_b": [0.05], "tbl_c": [0.1]},
        }
        all_pvals = {1: [0.01, 0.05, 0.1]}
        result = _call_r_combine(CollectedPvalues.from_dicts(per_table, all_pvals))
        assert result is not None
        assert result[1].cauchy_p == pytest.approx(2.31303843937040905e-02, rel=1e-6)
        assert result[1].hmp_p == pytest.approx(2.58759065818898529e-02, rel=1e-6)

    @requires_r
    def test_all_collapsed_one_fisher_stouffer_na(self):
        """When every per-table collapse = 1.0, Fisher/Stouffer return NA.
        R filters p < 1.0 and requires >= 2 valid values."""
        # 3 tables, each with 3 rows of moderate p-values → collapse: min(0.4)*3 = 1.2 → 1.0
        per_table = {
            1: {
                "tbl_a": [0.4, 0.5, 0.6],
                "tbl_b": [0.4, 0.5, 0.6],
                "tbl_c": [0.4, 0.5, 0.6],
            },
        }
        all_pvals = {1: [0.4, 0.5, 0.6, 0.4, 0.5, 0.6, 0.4, 0.5, 0.6]}
        result = _call_r_combine(CollectedPvalues.from_dicts(per_table, all_pvals))
        assert result is not None
        # Fisher and Stouffer: all collapsed values are 1.0, so NA
        assert result[1].fisher_p is None
        assert result[1].stouffer_p is None
        # CCT and HMP use raw p-values — should still compute
        assert result[1].cauchy_p is not None
        assert result[1].hmp_p is not None

    @requires_r
    def test_single_raw_pvalue_cct_identity(self):
        """ACAT with a single p-value returns approximately that value."""
        per_table = {1: {"tbl_a": [0.03]}}
        all_pvals = {1: [0.03]}
        result = _call_r_combine(CollectedPvalues.from_dicts(per_table, all_pvals))
        assert result is not None
        assert result[1].cauchy_p == pytest.approx(0.03, rel=1e-6)

    @requires_r
    def test_extreme_pvalue_survives_roundtrip(self):
        """A very small p-value (1e-200) survives the full pipeline."""
        per_table = {1: {"tbl_a": [1e-200], "tbl_b": [1e-100]}}
        all_pvals = {1: [1e-200, 1e-100]}
        result = _call_r_combine(CollectedPvalues.from_dicts(per_table, all_pvals))
        assert result is not None
        # Fisher should produce a very small combined p-value
        fisher_p = result[1].fisher_p
        assert fisher_p is not None
        assert fisher_p < 1e-50
        # CCT should also be very small
        cauchy_p = result[1].cauchy_p
        assert cauchy_p is not None
        assert cauchy_p < 1e-50


# ===================================================================
# 7. TestEndToEnd — full compute_combined_pvalues pipeline
# ===================================================================


class TestEndToEnd:
    def test_full_pipeline_no_r(self):
        """Without R, the table is created with NULL p-values but correct counts."""
        conn = _make_test_db()
        conn.execute("CREATE TABLE tbl_a (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_a VALUES (1, 0.01)")
        conn.execute("INSERT INTO tbl_a VALUES (2, 0.05)")
        conn.execute("CREATE TABLE tbl_a__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__link VALUES (1, 1)")
        conn.execute("INSERT INTO tbl_a__link VALUES (2, 1)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_a', 'pval', 'gene:tbl_a__link:target')"
        )
        conn.commit()

        with patch("shutil.which", return_value=None):
            compute_combined_pvalues(conn)

        row = conn.execute(
            "SELECT * FROM gene_combined_pvalues_target WHERE central_gene_id = 1"
        ).fetchone()
        assert row is not None
        # Column order: gene_id, fisher, fisher_fdr, stouffer, stouffer_fdr,
        #               cauchy, cauchy_fdr, hmp, hmp_fdr, num_tables, num_pvalues, gene_flags
        num_tables = row[9]
        num_pvalues = row[10]
        assert num_tables == 1
        assert num_pvalues == 2
        # All p-value columns should be None (R unavailable)
        assert row[1] is None  # fisher_pvalue
        assert row[3] is None  # stouffer_pvalue

    @requires_r
    def test_full_pipeline_with_r(self):
        """Full pipeline with R: 2 genes, 2 tables, verify results stored."""
        conn = _make_test_db()
        # Table A: gene 1 has row 1, gene 2 has row 2
        conn.execute("CREATE TABLE tbl_a (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_a VALUES (1, 0.001)")
        conn.execute("INSERT INTO tbl_a VALUES (2, 0.5)")
        conn.execute("CREATE TABLE tbl_a__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__link VALUES (1, 1)")
        conn.execute("INSERT INTO tbl_a__link VALUES (2, 2)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_a', 'pval', 'gene:tbl_a__link:target')"
        )
        # Table B: gene 1 has row 1
        conn.execute("CREATE TABLE tbl_b (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_b VALUES (1, 0.01)")
        conn.execute("CREATE TABLE tbl_b__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_b__link VALUES (1, 1)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_b', 'pval', 'gene:tbl_b__link:target')"
        )
        conn.commit()

        compute_combined_pvalues(conn, no_index=True)

        # Gene 1: 2 tables, 2 p-values → Fisher/Stouffer should have results
        row1 = conn.execute(
            "SELECT fisher_pvalue, stouffer_pvalue, cauchy_pvalue, hmp_pvalue, "
            "num_tables, num_pvalues FROM gene_combined_pvalues_target WHERE central_gene_id = 1"
        ).fetchone()
        assert row1 is not None
        assert row1[4] == 2  # num_tables
        assert row1[5] == 2  # num_pvalues
        assert row1[0] is not None  # fisher_pvalue
        assert row1[0] < 0.01  # should be very significant
        assert row1[1] is not None  # stouffer_pvalue
        assert row1[2] is not None  # cauchy_pvalue
        assert row1[3] is not None  # hmp_pvalue

        # Gene 2: 1 table, 1 p-value → Fisher/Stouffer should be None
        row2 = conn.execute(
            "SELECT fisher_pvalue, stouffer_pvalue, cauchy_pvalue, hmp_pvalue, "
            "num_tables, num_pvalues FROM gene_combined_pvalues_target WHERE central_gene_id = 2"
        ).fetchone()
        assert row2 is not None
        assert row2[4] == 1  # num_tables
        assert row2[5] == 1  # num_pvalues
        assert row2[0] is None  # fisher needs >= 2 values
        assert row2[1] is None  # stouffer needs >= 2 values
        assert row2[2] is not None  # cauchy works with 1 value
        assert row2[2] == pytest.approx(0.5, rel=1e-3)

    def test_no_hgnc_flag_for_missing_hgnc_id(self):
        """Gene with NULL hgnc_id gets 'no_hgnc' flag."""
        conn = _make_test_db()
        # Gene 3 has hgnc_id=NULL
        conn.execute("CREATE TABLE tbl_a (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_a VALUES (1, 0.01)")
        conn.execute("CREATE TABLE tbl_a__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__link VALUES (1, 3)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_a', 'pval', 'gene:tbl_a__link:target')"
        )
        conn.commit()

        with patch("processing.combined_pvalues.r_runner._call_r_combine", return_value={}):
            compute_combined_pvalues(conn)

        row = conn.execute(
            "SELECT gene_flags FROM gene_combined_pvalues_target WHERE central_gene_id = 3"
        ).fetchone()
        assert row is not None
        assert row[0] == "no_hgnc"

    def test_gene_with_hgnc_id_no_flag(self):
        """Gene with a valid hgnc_id (and no matching gene group) gets no flags."""
        conn = _make_test_db()
        conn.execute("CREATE TABLE tbl_a (id INTEGER, pval REAL)")
        conn.execute("INSERT INTO tbl_a VALUES (1, 0.01)")
        conn.execute("CREATE TABLE tbl_a__link (id INTEGER, central_gene_id INTEGER)")
        conn.execute("INSERT INTO tbl_a__link VALUES (1, 1)")
        conn.execute(
            "INSERT INTO data_tables (table_name, pvalue_column, link_tables) "
            "VALUES ('tbl_a', 'pval', 'gene:tbl_a__link:target')"
        )
        conn.commit()

        with patch("processing.combined_pvalues.r_runner._call_r_combine", return_value={}):
            compute_combined_pvalues(conn)

        row = conn.execute(
            "SELECT gene_flags FROM gene_combined_pvalues_target WHERE central_gene_id = 1"
        ).fetchone()
        assert row is not None
        assert row[0] is None  # BRCA1 has hgnc_id and no matching gene group


# ===================================================================
# 8. TestFilterCollected — pure dict filtering
# ===================================================================


class TestFilterCollected:
    def test_keeps_only_named_tables(self):
        master = CollectedPvalues.from_dicts(
            per_table={
                1: {"tbl_a": [0.01, 0.02], "tbl_b": [0.05]},
                2: {"tbl_a": [0.1], "tbl_c": [0.2]},
            },
            all_pvalues={1: [0.01, 0.02, 0.05], 2: [0.1, 0.2]},
        )
        out = _filter_collected(master, {"tbl_a"})
        assert dict(out.per_table) == {
            1: {"tbl_a": [0.01, 0.02]},
            2: {"tbl_a": [0.1]},
        }
        assert sorted(out.all_pvalues[1]) == [0.01, 0.02]
        assert sorted(out.all_pvalues[2]) == [0.1]

    def test_empty_filter_returns_empty(self):
        master = CollectedPvalues.from_dicts(
            per_table={1: {"tbl_a": [0.01]}}, all_pvalues={1: [0.01]},
        )
        out = _filter_collected(master, set())
        assert out.is_empty()

    def test_filter_with_no_matches_returns_empty(self):
        master = CollectedPvalues.from_dicts(
            per_table={1: {"tbl_a": [0.01]}}, all_pvalues={1: [0.01]},
        )
        out = _filter_collected(master, {"unrelated"})
        assert out.is_empty()

    def test_filter_does_not_mutate_master(self):
        """Ensure the filter creates fresh lists — mutating the output must not
        bleed back into master (a real risk with defaultdict-of-list)."""
        master = CollectedPvalues.from_dicts(
            per_table={1: {"tbl_a": [0.01, 0.02]}},
            all_pvalues={1: [0.01, 0.02]},
        )
        out = _filter_collected(master, {"tbl_a"})
        out.per_table[1]["tbl_a"].append(99.0)
        assert master.per_table[1]["tbl_a"] == [0.01, 0.02]


# ===================================================================
# 9. TestComputeGroupBuilder — pure group enumeration
# ===================================================================


def _make_row(
    table_name: str,
    *,
    pvalue_col: str = "pval",
    link: str = "g:lt:target",
    assay: str | None = None,
    disease: str | None = None,
    organism: str | None = None,
):
    return (table_name, pvalue_col, link, assay, disease, organism)


class TestComputeGroupBuilder:
    def test_emits_global_group_per_direction(self):
        rows = [_make_row("tbl_a")]
        groups = ComputeGroupBuilder(rows).build()
        out_tables = [g.out_table for g in groups]
        assert "gene_combined_pvalues_target" in out_tables
        assert "gene_combined_pvalues_perturbed" in out_tables

    def test_global_group_min_tables_one(self):
        rows = [_make_row("tbl_a")]
        groups = ComputeGroupBuilder(rows).build()
        global_groups = [
            g for g in groups
            if g.out_table.startswith("gene_combined_pvalues_")
            and g.assay_filter is None
            and g.disease_filter is None
            and g.organism_filter is None
        ]
        assert len(global_groups) == 2  # one per direction
        for g in global_groups:
            assert g.min_tables == 1

    def test_filter_groups_have_min_tables_two(self):
        rows = [
            _make_row("tbl_a", assay="rnaseq"),
            _make_row("tbl_b", assay="rnaseq"),
        ]
        groups = ComputeGroupBuilder(rows).build()
        assay_groups = [g for g in groups if g.assay_filter == "rnaseq"]
        assert assay_groups, "expected per-assay groups"
        for g in assay_groups:
            assert g.min_tables == 2

    def test_pairwise_and_triple_combos(self):
        rows = [
            _make_row(
                "tbl_x", assay="rnaseq", disease="asd", organism="human",
            ),
        ]
        groups = ComputeGroupBuilder(rows).build()
        out_tables = {g.out_table for g in groups}
        # 2 directions × {global, A, D, O, A+D, A+O, D+O, A+D+O} = 16 groups
        assert len(groups) == 16
        # spot-check a few names
        assert "gene_combined_pvalues_rnaseq_target" in out_tables
        assert "gene_combined_pvalues_d_asd_target" in out_tables
        assert "gene_combined_pvalues_o_human_target" in out_tables
        assert "gene_combined_pvalues_rnaseq_d_asd_target" in out_tables
        assert "gene_combined_pvalues_rnaseq_o_human_target" in out_tables
        assert "gene_combined_pvalues_d_asd_o_human_target" in out_tables
        assert "gene_combined_pvalues_rnaseq_d_asd_o_human_target" in out_tables

    def test_comma_separated_keys_split(self):
        rows = [_make_row("tbl_a", assay="rnaseq, atacseq")]
        groups = ComputeGroupBuilder(rows).build()
        assays = {g.assay_filter for g in groups if g.assay_filter}
        assert assays == {"rnaseq", "atacseq"}

    def test_empty_keys_skipped(self):
        rows = [_make_row("tbl_a", assay=None, disease="", organism="  ")]
        groups = ComputeGroupBuilder(rows).build()
        # Only direction-level globals should remain
        filtered = [
            g for g in groups
            if g.assay_filter or g.disease_filter or g.organism_filter
        ]
        assert filtered == []

    def test_groups_use_3col_table_triples(self):
        """ComputeGroup.tables drops the assay/disease/organism columns —
        only (table_name, pvalue_column, link_tables) flows downstream."""
        rows = [_make_row("tbl_a", pvalue_col="pv", link="g:lt:target")]
        groups = ComputeGroupBuilder(rows).build()
        for g in groups:
            for entry in g.tables:
                assert len(entry) == 3
                assert entry == ("tbl_a", "pv", "g:lt:target")


# ===================================================================
# 10. TestGeneFlagger — direct unit tests for the flag classifier
# ===================================================================


def _make_flagger_db(rows: list[tuple[int, str | None, str | None]]):
    """In-memory central_gene with the (id, human_symbol, hgnc_id) shape."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE central_gene ("
        "id INTEGER PRIMARY KEY, human_symbol TEXT, hgnc_id TEXT)"
    )
    for gid, sym, hgnc in rows:
        conn.execute(
            "INSERT INTO central_gene (id, human_symbol, hgnc_id) VALUES (?, ?, ?)",
            (gid, sym, hgnc),
        )
    conn.commit()
    return conn


class TestGeneFlagger:
    def test_no_flags_when_no_data(self):
        conn = _make_flagger_db([(1, "BRCA1", "HGNC:1100")])
        flagger = GeneFlagger.from_db(conn)
        assert flagger.flags_for(1) is None

    def test_no_hgnc_flag_when_id_missing(self):
        conn = _make_flagger_db([(1, "MYGENE", None)])
        flagger = GeneFlagger.from_db(conn)
        assert flagger.flags_for(1) == "no_hgnc"

    def test_hgnc_family_flag(self):
        flagger = GeneFlagger(
            symbol_lookup={1: "RPL5"},
            hgnc_id_lookup={1: "HGNC:10316"},
            hgnc_flags={"RPL5": "ribosomal"},
            nimh_genes=set(),
        )
        assert flagger.flags_for(1) == "ribosomal"

    def test_nimh_priority_flag(self):
        flagger = GeneFlagger(
            symbol_lookup={1: "BRCA1"},
            hgnc_id_lookup={1: "HGNC:1100"},
            hgnc_flags={},
            nimh_genes={"BRCA1"},
        )
        assert flagger.flags_for(1) == "nimh_priority"

    def test_combined_flags_sorted_comma_separated(self):
        flagger = GeneFlagger(
            symbol_lookup={1: "RPL5"},
            hgnc_id_lookup={1: None},
            hgnc_flags={"RPL5": "ribosomal,transcription_factor"},
            nimh_genes={"RPL5"},
        )
        # Flags merge from HGNC families + NIMH + missing-hgnc; alphabetized.
        assert flagger.flags_for(1) == (
            "nimh_priority,no_hgnc,ribosomal,transcription_factor"
        )

    def test_unknown_gene_id_with_no_hgnc_data(self):
        flagger = GeneFlagger(
            symbol_lookup={},
            hgnc_id_lookup={},
            hgnc_flags={},
            nimh_genes=set(),
        )
        # No symbol → not in NIMH; no hgnc id → no_hgnc fires.
        assert flagger.flags_for(99) == "no_hgnc"

    def test_from_db_skips_missing_paths(self, tmp_path: Path):
        conn = _make_flagger_db([(1, "BRCA1", "HGNC:1100")])
        # Pointing at non-existent paths should be silently ignored.
        flagger = GeneFlagger.from_db(
            conn,
            hgnc_path=tmp_path / "nope.tsv",
            nimh_csv_path=tmp_path / "nope.csv",
            tf_list_path=tmp_path / "nope.csv",
        )
        assert flagger.hgnc_flags == {}
        assert flagger.nimh_genes == set()
        assert flagger.flags_for(1) is None


# ===================================================================
# 11. TestRInputOutputBridging — _write_r_inputs / _parse_r_results
# ===================================================================


class TestWriteRInputs:
    def test_writes_collapsed_and_raw_csvs(self, tmp_path: Path):
        pvalues = CollectedPvalues.from_dicts(
            per_table={
                1: {"tbl_a": [0.01, 0.02]},  # min(0.01) * 2 = 0.02 collapsed
                2: {"tbl_a": [0.5], "tbl_b": [0.1]},
            },
            all_pvalues={1: [0.01, 0.02], 2: [0.5, 0.1]},
        )
        _write_r_inputs(tmp_path, pvalues)

        collapsed = list(csv.DictReader(open(tmp_path / "collapsed_pvalues.csv")))
        # Gene 1 collapses to 0.02; gene 2 emits two rows (one per table).
        assert len(collapsed) == 3
        gene1_rows = [r for r in collapsed if r["gene_id"] == "1"]
        assert len(gene1_rows) == 1
        assert float(gene1_rows[0]["pvalue"]) == pytest.approx(0.02, rel=1e-10)

        raw = list(csv.DictReader(open(tmp_path / "raw_pvalues.csv")))
        # 2 raws for gene 1 + 2 raws for gene 2 = 4 rows.
        assert len(raw) == 4
        gene1_raws = sorted(
            float(r["pvalue"]) for r in raw if r["gene_id"] == "1"
        )
        assert gene1_raws == pytest.approx([0.01, 0.02])

    def test_empty_pvalues_writes_only_headers(self, tmp_path: Path):
        _write_r_inputs(tmp_path, CollectedPvalues())
        for name in ("collapsed_pvalues.csv", "raw_pvalues.csv"):
            rows = list(csv.reader(open(tmp_path / name)))
            assert rows == [["gene_id", "pvalue"]]


class TestParseRResults:
    def _write_results_csv(self, path: Path, rows: list[dict[str, str]]):
        cols = [
            "gene_id",
            "fisher_p", "fisher_fdr",
            "stouffer_p", "stouffer_fdr",
            "cauchy_p", "cauchy_fdr",
            "hmp_p", "hmp_fdr",
        ]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_parses_full_row(self, tmp_path: Path):
        path = tmp_path / "results.csv"
        self._write_results_csv(path, [{
            "gene_id": "7",
            "fisher_p": "1e-3", "fisher_fdr": "1e-2",
            "stouffer_p": "2e-3", "stouffer_fdr": "2e-2",
            "cauchy_p": "3e-3", "cauchy_fdr": "3e-2",
            "hmp_p": "4e-3", "hmp_fdr": "4e-2",
        }])
        out = _parse_r_results(path)
        assert set(out.keys()) == {7}
        rec = out[7]
        assert rec.fisher_p == pytest.approx(1e-3)
        assert rec.fisher_fdr == pytest.approx(1e-2)
        assert rec.stouffer_p == pytest.approx(2e-3)
        assert rec.cauchy_fdr == pytest.approx(3e-2)
        assert rec.hmp_p == pytest.approx(4e-3)

    def test_na_inf_nan_become_none(self, tmp_path: Path):
        path = tmp_path / "results.csv"
        self._write_results_csv(path, [{
            "gene_id": "1",
            "fisher_p": "NA", "fisher_fdr": "",
            "stouffer_p": "NaN", "stouffer_fdr": "Inf",
            "cauchy_p": "-Inf", "cauchy_fdr": "0.5",
            "hmp_p": "0.25", "hmp_fdr": "NA",
        }])
        out = _parse_r_results(path)
        rec = out[1]
        assert rec.fisher_p is None
        assert rec.fisher_fdr is None
        assert rec.stouffer_p is None
        assert rec.stouffer_fdr is None
        assert rec.cauchy_p is None
        assert rec.cauchy_fdr == pytest.approx(0.5)
        assert rec.hmp_p == pytest.approx(0.25)
        assert rec.hmp_fdr is None

    def test_empty_results_csv(self, tmp_path: Path):
        path = tmp_path / "results.csv"
        self._write_results_csv(path, [])
        assert _parse_r_results(path) == {}
