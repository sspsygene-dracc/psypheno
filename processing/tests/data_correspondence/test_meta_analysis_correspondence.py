"""Meta-analysis spot-check: recompute combined p-values from per-table inputs
and compare against what's stored in `gene_combined_pvalues_*` (#113).

Slow + needs R. Skips cleanly if Rscript or the required packages are absent
(mirrors `processing/tests/test_combined_pvalues.py`'s gating).

Strategy:
  1. Pick `SAMPLE_SIZE` random `central_gene_id`s with `num_tables >= 2` in
     `gene_combined_pvalues_target` so there's actually meta-analysis going on.
  2. Build a `CollectedPvalues` from the live DB for the global-`target`
     direction, restricted to those genes.
  3. Call `r_runner.call_r_combine(...)` to recompute.
  4. Assert each gene's `fisher_p / cauchy_p / hmp_p` matches what the DB
     already stored, with `rel_tol=1e-6`. We don't compare FDRs — those are
     computed across the whole gene set, so a small subsample doesn't
     reproduce them.
"""

from __future__ import annotations

import random
import shutil
import sqlite3
import subprocess

import pytest

from processing.combined_pvalues.collection import collect_pvalues_for_tables
from processing.combined_pvalues.data import CollectedPvalues
from processing.combined_pvalues import r_runner

pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# R availability gate (mirrors processing/tests/test_combined_pvalues.py)
# ---------------------------------------------------------------------------

R_AVAILABLE = shutil.which("Rscript") is not None


def _r_packages_available() -> bool:
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

SAMPLE_SIZE = 20
SEED = 20260505


def _sample_gene_ids(db: sqlite3.Connection) -> list[int]:
    """Pick SAMPLE_SIZE genes that contributed to the global `target` table."""
    rows = db.execute(
        "SELECT central_gene_id FROM gene_combined_pvalues_target "
        "WHERE num_tables >= 2 AND fisher_pvalue IS NOT NULL"
    ).fetchall()
    ids = [r["central_gene_id"] for r in rows]
    rng = random.Random(SEED)
    rng.shuffle(ids)
    return ids[:SAMPLE_SIZE]


def _global_target_quads(db: sqlite3.Connection):
    """Mirror MetaAnalysisRun._load_source_tables filtered to the 4-tuple shape
    that `collect_pvalues_for_tables` consumes.
    """
    rows = db.execute(
        "SELECT table_name, pvalue_column, link_tables, effect_column "
        "FROM data_tables WHERE pvalue_column IS NOT NULL "
        "ORDER BY id ASC"
    ).fetchall()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


def _restrict_to_genes(
    full: CollectedPvalues, genes: set[int]
) -> CollectedPvalues:
    """Pull just the specified genes' entries out of a master CollectedPvalues."""
    out = CollectedPvalues()
    for gid in genes:
        if gid in full.per_table:
            for tbl, pvals in full.per_table[gid].items():
                out.per_table[gid][tbl] = list(pvals)
        if gid in full.all_pvalues:
            out.all_pvalues[gid] = list(full.all_pvalues[gid])
    return out


@requires_r
def test_combined_pvalues_match_db(db: sqlite3.Connection) -> None:
    """End-to-end: per-table p-values + R script → DB combined p-values."""
    sampled_ids = _sample_gene_ids(db)
    if len(sampled_ids) < 5:
        pytest.skip(
            f"only {len(sampled_ids)} genes with num_tables>=2 in "
            "gene_combined_pvalues_target — need ≥5 for a meaningful sample"
        )

    quads = _global_target_quads(db)
    master = collect_pvalues_for_tables(db, quads, direction="target", regulation="any")
    subset = _restrict_to_genes(master, set(sampled_ids))

    # Sanity: every sampled gene should have made it into the subset.
    missing = [g for g in sampled_ids if g not in subset.all_pvalues]
    assert not missing, (
        f"DB says {missing} contribute to gene_combined_pvalues_target but "
        "the live collection step didn't reproduce them — schema drift?"
    )

    recomputed = r_runner.call_r_combine(subset, use_cache=True)
    assert recomputed is not None, "call_r_combine returned None — R unavailable?"

    # Pull the stored values for comparison.
    placeholders = ",".join("?" * len(sampled_ids))
    stored_rows = db.execute(
        f"SELECT central_gene_id, fisher_pvalue, cauchy_pvalue, hmp_pvalue "
        f"FROM gene_combined_pvalues_target "
        f"WHERE central_gene_id IN ({placeholders})",
        list(sampled_ids),
    ).fetchall()
    stored = {r["central_gene_id"]: r for r in stored_rows}

    failures: list[str] = []
    for gid in sampled_ids:
        rec = recomputed.get(gid)
        s = stored.get(gid)
        if rec is None or s is None:
            failures.append(f"gene {gid}: missing in recomputed={rec is None} or db={s is None}")
            continue
        for label, rec_v, db_v in (
            ("fisher_p", rec.fisher_p, s["fisher_pvalue"]),
            ("cauchy_p", rec.cauchy_p, s["cauchy_pvalue"]),
            ("hmp_p", rec.hmp_p, s["hmp_pvalue"]),
        ):
            if rec_v is None and db_v is None:
                continue
            if rec_v is None or db_v is None:
                failures.append(
                    f"gene {gid} {label}: one side is None (rec={rec_v}, db={db_v})"
                )
                continue
            if abs(rec_v - db_v) > max(1e-9, 1e-6 * abs(db_v)):
                failures.append(
                    f"gene {gid} {label}: rec={rec_v} vs db={db_v} "
                    f"(diff={abs(rec_v - db_v):g})"
                )

    assert not failures, (
        f"{len(failures)} mismatch(es) between recomputed and stored:\n  "
        + "\n  ".join(failures[:10])
    )
