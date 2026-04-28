"""Pre-compute per-table effect-size distributions for the volcano/histogram UI.

For each ``data_tables`` row that declares both ``effect_column`` and
``pvalue_column``, we materialize:

- a 40-bin histogram of effect sizes between p1 and p99 (with extreme values
  clipped into the edge bins), and
- a downsampled volcano scatter (top-200 by smallest p-value + random 800).

Results are written to ``table_effect_distributions``; the API serves them as a
single SELECT, with the queried gene's effect/p value joined in at request time.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

HIST_BINS = 40
VOLCANO_TOP_BY_P = 200
VOLCANO_RANDOM = 800
VOLCANO_RANDOM_SEED = 42
PVALUE_FLOOR = 1e-300  # avoid -log10(0) = inf


@dataclass
class EffectHistogram:
    """Histogram bins shared by the API + frontend."""
    bin_edges: list[float]
    bin_counts: list[int]


@dataclass
class VolcanoPoint:
    effect: float
    neg_log10_p: float
    top_by_p: bool


@dataclass
class TableDistribution:
    table_name: str
    effect_column: str
    pvalue_column: str
    n_total: int
    n_nonnull: int
    histogram: EffectHistogram
    volcano_points: list[VolcanoPoint]


def compute_effect_distributions(
    conn: sqlite3.Connection, *, no_index: bool = False
) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE table_effect_distributions (
            table_name TEXT PRIMARY KEY,
            effect_column TEXT NOT NULL,
            pvalue_column TEXT NOT NULL,
            n_total INTEGER NOT NULL,
            n_nonnull INTEGER NOT NULL,
            bin_edges_json TEXT NOT NULL,
            bin_counts_json TEXT NOT NULL,
            volcano_points_json TEXT NOT NULL
        )"""
    )
    rows = cur.execute(
        """SELECT table_name, effect_column, pvalue_column
           FROM data_tables
           WHERE effect_column IS NOT NULL AND pvalue_column IS NOT NULL"""
    ).fetchall()
    logger.info(
        "Pre-computing effect-size distributions for %d table(s)", len(rows)
    )
    for table_name, effect_col, pval_col in rows:
        pval_col_first = pval_col.split(",")[0]
        dist = _compute_for_table(
            conn=conn,
            table_name=table_name,
            effect_column=effect_col,
            pvalue_column=pval_col_first,
        )
        if dist is None:
            logger.warning(
                "No usable effect data for %s; skipping distribution", table_name
            )
            continue
        cur.execute(
            """INSERT INTO table_effect_distributions
               (table_name, effect_column, pvalue_column, n_total, n_nonnull,
                bin_edges_json, bin_counts_json, volcano_points_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                dist.table_name,
                dist.effect_column,
                dist.pvalue_column,
                dist.n_total,
                dist.n_nonnull,
                json.dumps(dist.histogram.bin_edges),
                json.dumps(dist.histogram.bin_counts),
                json.dumps(
                    [
                        {
                            "e": p.effect,
                            "l": p.neg_log10_p,
                            "t": p.top_by_p,
                        }
                        for p in dist.volcano_points
                    ]
                ),
            ),
        )
    conn.commit()


def _compute_for_table(
    *,
    conn: sqlite3.Connection,
    table_name: str,
    effect_column: str,
    pvalue_column: str,
) -> TableDistribution | None:
    # Column names are stored lowercased & SQL-sanitized in data_tables, and the
    # underlying per-dataset tables have the same convention, so a quoted
    # identifier lookup is safe. SQLite quotes are double-quote.
    sql = (
        f'SELECT "{effect_column}" AS effect, "{pvalue_column}" AS pvalue '
        f'FROM "{table_name}"'
    )
    df = pd.read_sql_query(sql, conn)
    n_total = len(df)
    df_clean = df.dropna(subset=["effect"]).copy()
    df_clean["effect"] = pd.to_numeric(df_clean["effect"], errors="coerce")
    df_clean = df_clean.dropna(subset=["effect"])
    n_nonnull = len(df_clean)
    if n_nonnull == 0:
        return None
    histogram = _compute_histogram(df_clean["effect"].to_numpy(dtype=float))
    df_with_pval = df_clean.copy()
    df_with_pval["pvalue"] = pd.to_numeric(df_with_pval["pvalue"], errors="coerce")
    df_with_pval = df_with_pval.dropna(subset=["pvalue"])
    volcano = _compute_volcano(df_with_pval)
    return TableDistribution(
        table_name=table_name,
        effect_column=effect_column,
        pvalue_column=pvalue_column,
        n_total=n_total,
        n_nonnull=n_nonnull,
        histogram=histogram,
        volcano_points=volcano,
    )


def _compute_histogram(effects: np.ndarray) -> EffectHistogram:
    if len(effects) == 0:
        return EffectHistogram(bin_edges=[-0.5, 0.5], bin_counts=[0])
    p_low, p_high = np.percentile(effects, [1, 99])
    if p_low == p_high:
        # Distribution dominated by a single value (e.g. all-zero column);
        # fall back to min/max so we still produce a meaningful range.
        p_low_v, p_high_v = float(effects.min()), float(effects.max())
        if p_low_v == p_high_v:
            return EffectHistogram(
                bin_edges=[p_low_v - 0.5, p_low_v + 0.5],
                bin_counts=[int(len(effects))],
            )
        p_low, p_high = p_low_v, p_high_v
    clipped = np.clip(effects, p_low, p_high)
    counts, edges = np.histogram(clipped, bins=HIST_BINS, range=(float(p_low), float(p_high)))
    return EffectHistogram(
        bin_edges=[float(e) for e in edges],
        bin_counts=[int(c) for c in counts],
    )


def _compute_volcano(df: pd.DataFrame) -> list[VolcanoPoint]:
    if len(df) == 0:
        return []
    pvals = df["pvalue"].clip(lower=PVALUE_FLOOR)
    df = df.assign(neg_log10p=-np.log10(pvals))
    top_n = min(VOLCANO_TOP_BY_P, len(df))
    top = df.nlargest(top_n, "neg_log10p")
    rest_pool = df.drop(top.index)
    rest_n = min(VOLCANO_RANDOM, len(rest_pool))
    if rest_n > 0:
        rest = rest_pool.sample(n=rest_n, random_state=VOLCANO_RANDOM_SEED)
    else:
        rest = rest_pool.iloc[:0]
    out: list[VolcanoPoint] = []
    for _, row in top.iterrows():
        out.append(
            VolcanoPoint(
                effect=float(row["effect"]),
                neg_log10_p=float(row["neg_log10p"]),
                top_by_p=True,
            )
        )
    for _, row in rest.iterrows():
        out.append(
            VolcanoPoint(
                effect=float(row["effect"]),
                neg_log10_p=float(row["neg_log10p"]),
                top_by_p=False,
            )
        )
    return out
