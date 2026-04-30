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

Combine implementations are reference-grade (matching poolr / ACAT) but in
pure Python so we can sweep scenarios without spinning up R.

Usage:
    SSPSYGENE_DATA_DB=/path/to/sspsygene.db \\
        processing/.venv-claude/bin/python processing/scripts/pvalue_filter_experiment.py
"""

import math
import os
import sqlite3
import sys
from collections import defaultdict

import numpy as np
from scipy import stats

DB = os.environ.get("SSPSYGENE_DATA_DB", "data/db/sspsygene.db")

# Already-DEG-only tables (per the §1 audit in #148). Unaffected by C(T)
# filtering; flagged in the table listing for context.
PREFILTERED = {
    "brain_organoid_atlas_nebula_gene_0_05_FDR",
    "brain_organoid_atlas_nebula_gene_0_2_FDR",
    "mouse_perturb_deg",
}


def parse_link_tables(link_tables_raw: str, direction: str):
    """Return list of (data_column, link_table_name) for the given direction."""
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


def load_data(cur):
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


# --- combine functions ----------------------------------------------------


def precollapse_per_table(pvals: list[float]) -> float:
    """Bonferroni: min(p) * n, capped at 1."""
    return min(min(pvals) * len(pvals), 1.0)


def fisher_combine(pvals: list[float]) -> float | None:
    """-2 sum log p ~ chi2(2k). Drop p>=1 (no information)."""
    valid = [p for p in pvals if 0 < p < 1]
    if len(valid) < 2:
        return None
    chi2 = -2.0 * sum(math.log(p) for p in valid)
    return float(stats.chi2.sf(chi2, 2 * len(valid)))


def stouffer_combine(pvals: list[float]) -> float | None:
    """sum z_i / sqrt(k), z_i = qnorm(1-p). Drop p>=1."""
    valid = [p for p in pvals if 0 < p < 1]
    if len(valid) < 2:
        return None
    zs = stats.norm.isf(np.array(valid))
    z = float(zs.sum() / math.sqrt(len(valid)))
    return float(stats.norm.sf(z))


def cct_combine(pvals: list[float]) -> float | None:
    """Cauchy combination test (ACAT, equal weights)."""
    valid = [p for p in pvals if 0 < p < 1]
    if len(valid) < 2:
        return None
    parts = []
    for p in valid:
        if p < 1e-15:
            parts.append(1.0 / (p * math.pi))
        else:
            parts.append(math.tan((0.5 - p) * math.pi))
    T = sum(parts) / len(valid)
    if T > 1e15:
        return float(1.0 / (T * math.pi))
    return float(0.5 - math.atan(T) / math.pi)


def combine_all_genes(gene_pvals, scenario_filter):
    """{gene_id: (fisher_p, stouffer_p, cct_p)} for the given scenario filter."""
    per_gene_table: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for table_name, gdict in gene_pvals.items():
        for gid, ps in gdict.items():
            kept = [p for p in ps if scenario_filter(table_name, p)]
            if kept:
                per_gene_table[gid][table_name] = kept

    out = {}
    for gid, tbl_dict in per_gene_table.items():
        collapsed = [precollapse_per_table(ps) for ps in tbl_dict.values()]
        raw = [p for ps in tbl_dict.values() for p in ps]
        out[gid] = (
            fisher_combine(collapsed),
            stouffer_combine(collapsed),
            cct_combine(raw),
        )
    return out


# --- ranking comparison ---------------------------------------------------


def rank_by(d, idx):
    items = [(gid, vals[idx]) for gid, vals in d.items() if vals[idx] is not None]
    items.sort(key=lambda x: x[1])
    return items


def top_overlap(rank_a, rank_b, k):
    a = {g for g, _ in rank_a[:k]}
    b = {g for g, _ in rank_b[:k]}
    return len(a & b) / k if k else 1.0


def spearman_top(rank_a, rank_b, k):
    a_top = {g: i for i, (g, _) in enumerate(rank_a[:k])}
    b_top = {g: i for i, (g, _) in enumerate(rank_b[:k])}
    union = list(a_top.keys() | b_top.keys())
    if len(union) < 3:
        return float("nan")
    a_ranks = [a_top.get(g, k) for g in union]
    b_ranks = [b_top.get(g, k) for g in union]
    rho, _ = stats.spearmanr(a_ranks, b_ranks)
    return rho


# --- main -----------------------------------------------------------------


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
            f"  {short_label[tn][:42]:<43} {tn:<45} "
            f"genes={len(g):>6} rows={n_rows:>9}{flag}"
        )
    print()

    print("Computing combined p under each scenario...")
    A = combine_all_genes(gene_pvals, lambda _t, _p: True)
    Cs = {
        T: combine_all_genes(gene_pvals, (lambda T_=T: lambda _t, p: p <= T_)())
        for T in (0.05, 0.1, 0.2, 0.5)
    }
    print(
        f"A: {len(A)} genes, "
        + ", ".join(f"C({T}): {len(C)}" for T, C in Cs.items())
    )

    METHODS = [("Fisher", 0), ("Stouffer", 1), ("CCT", 2)]
    KS = [50, 100, 500, 1000]

    def report(label, X, Y):
        print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")
        print(
            f"{'method':<10} "
            + " ".join(f"{'top' + str(k) + '_jacc':>13}" for k in KS)
            + "  "
            + " ".join(f"{'top' + str(k) + '_rho':>11}" for k in KS)
        )
        for name, idx in METHODS:
            rX = rank_by(X, idx)
            rY = rank_by(Y, idx)
            overlaps = [top_overlap(rX, rY, k) for k in KS]
            rhos = [spearman_top(rX, rY, k) for k in KS]
            print(
                f"{name:<10} "
                + " ".join(f"{o:>13.3f}" for o in overlaps)
                + "  "
                + " ".join(f"{r:>11.3f}" for r in rhos)
            )

    for T, C in Cs.items():
        report(f"A = baseline   C(T={T}) = filter every table at p<={T}", A, C)

    return 0


if __name__ == "__main__":
    sys.exit(main())
