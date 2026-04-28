"""Pre-compute per-table volcano-plot scatter samples.

For each ``data_tables`` row that declares both ``effect_column`` and
``pvalue_column``, we materialize a downsampled volcano scatter (top-200
by smallest p-value + random 800) — that's what the gene-search page renders
in each per-table card. Each point carries the effect, the p-value, and the
FDR (when the table has an FDR column), so the frontend can color by the
FDR≤0.05 (falling back to p-value≤0.05) significance threshold.

The histogram view that originally accompanied the volcano was removed per
Max's 2026-04-28 feedback — the gene's marker on the volcano already answers
"where does my gene fall in this study's distribution".
"""

import json
import logging
import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

VOLCANO_TOP_BY_P = 200
VOLCANO_RANDOM = 800
VOLCANO_RANDOM_SEED = 42
PVALUE_FLOOR = 1e-300  # avoid -log10(0) = inf


@dataclass
class VolcanoPoint:
    effect: float
    neg_log10_p: float
    fdr: float | None
    top_by_p: bool


@dataclass
class TableDistribution:
    table_name: str
    effect_column: str
    pvalue_column: str
    fdr_column: str | None
    n_total: int
    n_nonnull: int
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
            fdr_column TEXT,
            n_total INTEGER NOT NULL,
            n_nonnull INTEGER NOT NULL,
            volcano_points_json TEXT NOT NULL
        )"""
    )
    rows = cur.execute(
        """SELECT table_name, effect_column, pvalue_column, fdr_column
           FROM data_tables
           WHERE effect_column IS NOT NULL AND pvalue_column IS NOT NULL"""
    ).fetchall()
    logger.info("Pre-computing effect-size distributions for %d table(s)", len(rows))
    for table_name, effect_col, pval_col, fdr_col in rows:
        pval_col_first = pval_col.split(",")[0]
        fdr_col_first = (fdr_col or "").split(",")[0] or None
        dist = _compute_for_table(
            conn=conn,
            table_name=table_name,
            effect_column=effect_col,
            pvalue_column=pval_col_first,
            fdr_column=fdr_col_first,
        )
        if dist is None:
            logger.warning(
                "No usable effect data for %s; skipping distribution", table_name
            )
            continue
        cur.execute(
            """INSERT INTO table_effect_distributions
               (table_name, effect_column, pvalue_column, fdr_column,
                n_total, n_nonnull, volcano_points_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                dist.table_name,
                dist.effect_column,
                dist.pvalue_column,
                dist.fdr_column,
                dist.n_total,
                dist.n_nonnull,
                json.dumps(
                    [
                        {
                            "e": p.effect,
                            "l": p.neg_log10_p,
                            "f": p.fdr,
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
    fdr_column: str | None,
) -> TableDistribution | None:
    select_cols = [
        f'"{effect_column}" AS effect',
        f'"{pvalue_column}" AS pvalue',
    ]
    if fdr_column:
        select_cols.append(f'"{fdr_column}" AS fdr')
    sql = f'SELECT {", ".join(select_cols)} FROM "{table_name}"'
    df = pd.read_sql_query(sql, conn)
    if "fdr" not in df.columns:
        df["fdr"] = pd.NA
    n_total = len(df)
    df_clean = df.dropna(subset=["effect"]).copy()
    df_clean["effect"] = pd.to_numeric(df_clean["effect"], errors="coerce")
    df_clean = df_clean.dropna(subset=["effect"])
    n_nonnull = len(df_clean)
    if n_nonnull == 0:
        return None
    df_with_pval = df_clean.copy()
    df_with_pval["pvalue"] = pd.to_numeric(df_with_pval["pvalue"], errors="coerce")
    df_with_pval = df_with_pval.dropna(subset=["pvalue"])
    df_with_pval["fdr"] = pd.to_numeric(df_with_pval["fdr"], errors="coerce")
    volcano = _compute_volcano(df_with_pval)
    return TableDistribution(
        table_name=table_name,
        effect_column=effect_column,
        pvalue_column=pvalue_column,
        fdr_column=fdr_column,
        n_total=n_total,
        n_nonnull=n_nonnull,
        volcano_points=volcano,
    )


def _compute_volcano(df: pd.DataFrame) -> list[VolcanoPoint]:
    if len(df) == 0:
        return []
    pvals = df["pvalue"].clip(lower=PVALUE_FLOOR)
    df = df.assign(neg_log10p=-np.log10(pvals))
    top_n = min(VOLCANO_TOP_BY_P, len(df))
    top = df.nlargest(top_n, "neg_log10p")
    rest_pool = df.drop(top.index)  # type: ignore
    rest_n = min(VOLCANO_RANDOM, len(rest_pool))
    if rest_n > 0:
        rest = rest_pool.sample(n=rest_n, random_state=VOLCANO_RANDOM_SEED)
    else:
        rest = rest_pool.iloc[:0]
    out: list[VolcanoPoint] = []
    for chunk, top_flag in ((top, True), (rest, False)):
        for _, row in chunk.iterrows():
            fdr_raw = row.get("fdr")
            fdr_val = (
                None
                if fdr_raw is None or pd.isna(fdr_raw)
                else float(fdr_raw)
            )
            out.append(
                VolcanoPoint(
                    effect=float(row["effect"]),
                    neg_log10_p=float(row["neg_log10p"]),
                    fdr=fdr_val,
                    top_by_p=top_flag,
                )
            )
    return out
