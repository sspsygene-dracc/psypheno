"""Audit per-table p-value distributions against the U[0,1]-under-null assumption.

The combined-p pipeline (Fisher / Stouffer / Cauchy / HMP) requires each input
p-value to be ~U[0,1] under H0. This script pulls every row from each table
that registers a `pvalue_column` in `data_tables` and reports a coarse
histogram plus a one-sample KS distance from U[0,1], so violations
(pre-filtered tables, p=1 sentinel spikes, heavy left skew) are visible at a
glance.

Usage:
    SSPSYGENE_DATA_DB=/path/to/sspsygene.db \\
        processing/.venv-claude/bin/python processing/scripts/pvalue_distribution_audit.py

Filed alongside sspsygene-dracc/psypheno#148.
"""

import os
import sqlite3
import sys

DB = os.environ.get("SSPSYGENE_DATA_DB", "data/db/sspsygene.db")

BINS = [0, 0.001, 0.01, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]
BIN_LABELS = [
    "<.001", ".001-.01", ".01-.05", ".05-.1", ".1-.2", ".2-.3", ".3-.4",
    ".4-.5", ".5-.6", ".6-.7", ".7-.8", ".8-.9", ".9-1",
]


def bin_idx(p: float) -> int:
    for i in range(len(BINS) - 1):
        if BINS[i] <= p < BINS[i + 1]:
            return i
    return len(BINS) - 2


def ks_uniform_stat(pvals: list[float]) -> float | None:
    """One-sample two-sided KS distance from U[0,1]."""
    n = len(pvals)
    if n == 0:
        return None
    s = sorted(pvals)
    d_plus = max((i + 1) / n - s[i] for i in range(n))
    d_minus = max(s[i] - i / n for i in range(n))
    return max(d_plus, d_minus)


def main() -> int:
    if not os.path.exists(DB):
        print(f"DB not found at {DB} (set SSPSYGENE_DATA_DB)", file=sys.stderr)
        return 1

    con = sqlite3.connect(DB)
    cur = con.cursor()

    tables = cur.execute(
        """
        SELECT table_name, short_label, pvalue_column, assay
        FROM data_tables
        WHERE pvalue_column IS NOT NULL AND pvalue_column != ''
        ORDER BY table_name
        """
    ).fetchall()

    print(
        f"{'short_label':<46} {'assay':<13} {'N':>9} {'p<0.001':>8} "
        f"{'<0.01':>6} {'<0.05':>6} {'>0.5':>6} {'mean':>6} {'expU':>6} {'KSstat':>7}"
    )
    print("-" * 130)

    results = []
    for table_name, short_label, pcol, assay in tables:
        rows = cur.execute(
            f"SELECT {pcol} FROM {table_name} WHERE {pcol} IS NOT NULL"
        ).fetchall()
        pvals = [r[0] for r in rows if r[0] is not None and 0 <= r[0] <= 1]
        n = len(pvals)
        if n == 0:
            continue
        counts = [0] * (len(BINS) - 1)
        for p in pvals:
            counts[bin_idx(p)] += 1
        mean = sum(pvals) / n
        n_lt_001 = sum(1 for p in pvals if p < 0.001)
        n_lt_01 = sum(1 for p in pvals if p < 0.01)
        n_lt_05 = sum(1 for p in pvals if p < 0.05)
        n_gt_5 = sum(1 for p in pvals if p > 0.5)
        ks = ks_uniform_stat(pvals)
        print(
            f"{short_label[:45]:<46} {(assay or '')[:12]:<13} {n:>9} "
            f"{n_lt_001 / n:>8.1%} {n_lt_01 / n:>6.1%} {n_lt_05 / n:>6.1%} "
            f"{n_gt_5 / n:>6.1%} {mean:>6.3f} {0.5:>6.3f} {ks:>7.3f}"
        )
        results.append((short_label, n, counts))

    print()
    print("Coarse histogram (each row = % of rows in bin):")
    print("Bins: " + " | ".join(f"[{BINS[i]:.3g},{BINS[i + 1]:.3g})" for i in range(len(BINS) - 1)))
    print()
    print(f"{'short_label':<46} " + " ".join(f"{b:>8}" for b in BIN_LABELS))
    for short_label, n, counts in results:
        pcts = [c / n * 100 for c in counts]
        print(f"{short_label[:45]:<46} " + " ".join(f"{p:>8.1f}" for p in pcts))

    return 0


if __name__ == "__main__":
    sys.exit(main())
