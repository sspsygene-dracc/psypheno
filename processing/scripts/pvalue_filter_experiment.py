"""How much does the bulk of non-significant p-values move the meta-analysis ranking?

The histogram audit (`pvalue_distribution_audit.py`, sspsygene-dracc/psypheno#148)
shows that input p-values violate U[0,1] under H0 — the worst case being
already-DEG-only tables that store only p < 0.05. This script asks the
practical question: do the rankings the UI shows actually change when we
artificially impose the same DEG-only filter on every table?

Compares two scenarios for the target-direction combine:

  A         baseline      every table, every row, as-is.
  C(T)      filter all    drop rows with p > T from every table.
                          Already-filtered tables are unaffected (no rows
                          above T to drop).

If A and C(T) give the same top-K, the non-significant tail above T isn't
contributing meaningful ranking information at the top of the list, and the
mixed-filtering bias is mostly a concern for combined-p *magnitudes*, not
gene rankings. If they disagree, the bias is real for ranking too.

Combine is delegated to the same R script the production pipeline uses
(`processing/src/processing/r/compute_combined.R`, which calls poolr::fisher,
poolr::stouffer, ACAT::ACAT, harmonicmeanp::p.hmp), so all four reported
methods match the production implementations exactly.

Usage:
    SSPSYGENE_DATA_DB=/path/to/sspsygene.db \\
        processing/.venv-claude/bin/python processing/scripts/pvalue_filter_experiment.py
"""

# pylint: disable=invalid-name,too-many-locals

import csv
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Callable, cast

import mpmath
from scipy import stats

DB = os.environ.get("SSPSYGENE_DATA_DB", "data/db/sspsygene.db")
R_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "processing"
    / "r"
    / "compute_combined.R"
)

PREFILTERED = {
    "brain_organoid_atlas_nebula_gene_0_05_FDR",
    "brain_organoid_atlas_nebula_gene_0_2_FDR",
    "mouse_perturb_deg",
}

ScenarioFilter = Callable[[str, float], bool]


def parse_link_tables(link_tables_raw: str, direction: str) -> list[tuple[str, str]]:
    out = []
    for entry in (link_tables_raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 3:
            continue
        col_name, link_table_name, dir_ = parts[0], parts[1], parts[2]
        if dir_ == direction:
            out.append((col_name, link_table_name))
    return out


def load_data(
    cur: sqlite3.Cursor,
) -> tuple[dict[str, dict[int, list[float]]], dict[str, str]]:
    """{table_name: {central_gene_id: [p, ...]}} for target-direction tables."""
    tables = cur.execute(
        """
        SELECT table_name, short_label, pvalue_column, link_tables
        FROM data_tables
        WHERE pvalue_column IS NOT NULL AND pvalue_column != ''
        """
    ).fetchall()

    gene_pvals: dict[str, dict[int, list[float]]] = {}
    short_label = {}
    for table_name, label, pcol, link_raw in tables:
        targets = parse_link_tables(link_raw, "target")
        if not targets:
            continue
        short_label[table_name] = label
        g: dict[int, list[float]] = defaultdict(list)
        for _col, link_table in targets:
            rows = cur.execute(
                f"SELECT lt.central_gene_id, t.{pcol} "
                f'FROM "{link_table}" lt '
                f'JOIN "{table_name}" t ON t.id = lt.id '
                f"WHERE t.{pcol} IS NOT NULL"
            ).fetchall()
            for gid, p in rows:
                if p is None or p < 0 or p > 1:
                    continue
                g[gid].append(p)
        if g:
            gene_pvals[table_name] = g
    return gene_pvals, short_label


def precollapse(pvals: list[float]) -> float:
    """Bonferroni: min(p) * n, capped at 1, mpmath for tiny p (matches pipeline)."""
    n = len(pvals)
    min_p = mpmath.mpf(min(pvals))
    return float(min(min_p * n, mpmath.mpf(1)))


def run_r_combine(
    per_gene_table: dict[int, dict[str, list[float]]],
    label: str,
) -> dict[int, tuple[float | None, ...]]:
    """Write CSVs, call R, return {gene_id: (fisher, stouffer, cct, hmp)}.

    Mirrors processing/src/processing/combined_pvalues.py:call_r_combine
    but built on already-filtered in-memory data.
    """
    rscript = shutil.which("Rscript")
    if rscript is None:
        sys.exit("Rscript not found on PATH")
    if not R_SCRIPT.exists():
        sys.exit(f"R script not found: {R_SCRIPT}")

    tmp_dir = tempfile.mkdtemp(prefix=f"sspsygene_filterexp_{label}_")
    try:
        collapsed_path = Path(tmp_dir) / "collapsed_pvalues.csv"
        with open(collapsed_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["gene_id", "pvalue"])
            for gid in sorted(per_gene_table.keys()):
                for tbl_pvals in per_gene_table[gid].values():
                    w.writerow([gid, f"{precollapse(tbl_pvals):.17e}"])

        raw_path = Path(tmp_dir) / "raw_pvalues.csv"
        with open(raw_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["gene_id", "pvalue"])
            for gid in sorted(per_gene_table.keys()):
                for tbl_pvals in per_gene_table[gid].values():
                    for p in tbl_pvals:
                        w.writerow([gid, f"{p:.17e}"])

        print(
            f"  [{label}] calling R ({sum(len(v) for v in per_gene_table.values())} gene-tables)..."
        )
        result = subprocess.run(
            [rscript, str(R_SCRIPT), tmp_dir],
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            sys.exit(f"R failed for scenario {label}")

        # forward R's progress lines so it doesn't look hung
        for line in result.stdout.strip().splitlines():
            print(f"  [{label}] {line.strip()}")

        results_path = Path(tmp_dir) / "results.csv"
        out: dict[int, tuple[float | None, ...]] = {}

        def parse(s: str) -> float | None:
            if s in ("NA", "", "NaN", "Inf", "-Inf"):
                return None
            try:
                v = float(s)
            except ValueError:
                return None
            if math.isnan(v) or math.isinf(v):
                return None
            return v

        with open(results_path) as f:
            for row in csv.DictReader(f):
                gid = int(row["gene_id"])
                out[gid] = (
                    parse(row["fisher_p"]),
                    parse(row["stouffer_p"]),
                    parse(row["cauchy_p"]),
                    parse(row["hmp_p"]),
                )
        return out
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def build_per_gene_table(
    gene_pvals: dict[str, dict[int, list[float]]],
    scenario_filter: ScenarioFilter,
) -> dict[int, dict[str, list[float]]]:
    """{gene_id: {table_name: [p,...]}}, retaining only rows that pass the filter."""
    per: dict[int, dict[str, list[float]]] = defaultdict(dict)
    for table_name, gdict in gene_pvals.items():
        for gid, ps in gdict.items():
            kept = [p for p in ps if scenario_filter(table_name, p)]
            if kept:
                per[gid][table_name] = kept
    return per


def rank_by(
    d: dict[int, tuple[float | None, ...]], idx: int
) -> list[tuple[int, float]]:
    items: list[tuple[int, float]] = []
    for gid, vals in d.items():
        v = vals[idx]
        if v is not None:
            items.append((gid, v))
    items.sort(key=lambda x: x[1])
    return items


def top_overlap(
    rA: list[tuple[int, float]], rB: list[tuple[int, float]], k: int
) -> float:
    a = {g for g, _ in rA[:k]}
    b = {g for g, _ in rB[:k]}
    return len(a & b) / k if k else 1.0


def spearman_top(
    rA: list[tuple[int, float]], rB: list[tuple[int, float]], k: int
) -> float:
    a_top = {g: i for i, (g, _) in enumerate(rA[:k])}
    b_top = {g: i for i, (g, _) in enumerate(rB[:k])}
    union = list(a_top.keys() | b_top.keys())
    if len(union) < 3:
        return float("nan")
    ar = [a_top.get(g, k) for g in union]
    br = [b_top.get(g, k) for g in union]
    rho, _ = stats.spearmanr(ar, br)
    return cast(float, rho)


def main() -> int:
    if not os.path.exists(DB):
        print(f"DB not found at {DB} (set SSPSYGENE_DATA_DB)", file=sys.stderr)
        return 1

    con = sqlite3.connect(DB)
    cur = con.cursor()

    gene_pvals, short_label = load_data(cur)
    print(f"Loaded {len(gene_pvals)} target-direction tables:")
    for tn, g in gene_pvals.items():
        n_rows = sum(len(v) for v in g.values())
        flag = "  [pre-filtered]" if tn in PREFILTERED else ""
        print(
            f"  {short_label[tn][:42]:<43} {tn:<45} genes={len(g):>6} rows={n_rows:>9}{flag}"
        )
    print()

    scenarios: list[tuple[str, ScenarioFilter]] = [
        ("baseline", lambda _t, _p: True),
    ]
    for T in (0.05, 0.1, 0.2, 0.5):
        scenarios.append((f"C{T}", lambda _t, p, T_=T: p <= T_))

    print("Running R combine for each scenario; takes a few minutes total.\n")
    results: dict[str, dict[int, tuple[float | None, ...]]] = {}
    for label, flt in scenarios:
        per = build_per_gene_table(gene_pvals, flt)
        results[label] = run_r_combine(per, label)
        print(f"  [{label}] {len(results[label])} genes scored\n")

    METHODS = [("Fisher", 0), ("Stouffer", 1), ("CCT", 2), ("HMP", 3)]
    KS = [50, 100, 500, 1000]
    A = results["baseline"]

    for label, _ in scenarios[1:]:
        C = results[label]
        T = label[1:]
        print(
            f"\n{'=' * 96}\nA = baseline   C(T={T}) = filter every table at p<={T}\n{'=' * 96}"
        )
        print(
            f"{'method':<10} "
            + " ".join(f"{'top' + str(k) + '_jacc':>13}" for k in KS)
            + "  "
            + " ".join(f"{'top' + str(k) + '_rho':>11}" for k in KS)
        )
        for name, idx in METHODS:
            rA = rank_by(A, idx)
            rC = rank_by(C, idx)
            ovs = [top_overlap(rA, rC, k) for k in KS]
            rhs = [spearman_top(rA, rC, k) for k in KS]
            print(
                f"{name:<10} "
                + " ".join(f"{o:>13.3f}" for o in ovs)
                + "  "
                + " ".join(f"{r:>11.3f}" for r in rhs)
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
