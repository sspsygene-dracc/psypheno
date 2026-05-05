"""Per-(table, row) value correspondence: raw CSV → DB end-to-end (#113).

Local-only: marked `slow`, needs the gitignored data and the live SQLite.

Two assertions per sampled row:

  1. **In-path → DB.** The cleaned CSV (or raw CSV when there's no
     preprocess.py) at row index `i` must match the DB row with `id == i`,
     cell-for-cell, for every column the DB carries. This is the
     load-db invariant: `load_data_table` reads the file as-is and does not
     transform values.

  2. **Raw → cleaned.** When the raw file is also on disk and the
     preprocessing run dropped 0 rows (so row indices line up), each
     non-gene column must round-trip unchanged from raw to cleaned. The
     gene column itself becomes `<col>_raw` in the cleaned CSV; we check
     that it carries the original value forward so the DB's `<col>_raw`
     reflects exactly what the wrangler shipped.

Tables that drop rows or transform via `transform_column` skip part (2)
because raw-row-index → cleaned-row-index isn't a stable mapping.
"""

from __future__ import annotations

import math
import random
import sqlite3
from typing import Any

import pandas as pd
import pytest

from .helpers import (
    PrimaryTable,
    _normalize_col,
    enumerate_primary_tables,
    load_sidecar,
    manifest_entry_for,
    payload_dataset_dir,
    sidecar_drop_total,
)

pytestmark = pytest.mark.slow

# Determinism: same RNG seed → same sampled rows on every run.
SEED = 20260505
SAMPLE_SIZE = 50
GENE_RNG = random.Random(SEED)


def _read_csv(dataset: str, filename: str, sep: str) -> pd.DataFrame | None:
    p = payload_dataset_dir(dataset) / filename
    if not p.exists():
        return None
    return pd.read_csv(p, sep=sep, dtype=str, keep_default_na=False, na_values=[""])


def _has_only_count_neutral_steps(sidecar: dict[str, Any] | None) -> bool:
    """True if every action is row-preserving and value-preserving for non-gene
    columns. Gates the raw → cleaned spot-check.

    `transform_column` mutates a non-gene column by definition; if any pipeline
    has it we skip the round-trip check.
    """
    if sidecar is None:
        return True
    for action in sidecar.get("actions", []) or []:
        step = action.get("step")
        if step in ("dropna", "filter_rows"):
            if int(action.get("dropped", 0) or 0) > 0:
                return False
        elif step == "clean_gene_column":
            if int(action.get("dropped_rows", 0) or 0) > 0:
                return False
        elif step == "transform_column":
            return False
    return True


# Pandas reads NA/NaN strings as NaN by default; we read with
# `keep_default_na=False` so the literal sentinel survives. Treat all of
# these as equivalent to a SQLite NULL or to a NaN float — they're all
# "missing" from the data-quality test's point of view.
_MISSING_SENTINELS = frozenset({"", "NA", "N/A", "NaN", "nan", "None"})


def _is_missing(v: object) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and v in _MISSING_SENTINELS:
        return True
    return False


def _values_close(a: object, b: object) -> bool:
    """Equality with float tolerance and missing-value handling."""
    if _is_missing(a) and _is_missing(b):
        return True
    if _is_missing(a) or _is_missing(b):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    return a == b


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def _sample_rows(num_samples: int) -> list[tuple[PrimaryTable, int]]:
    """Pick (table, row_idx) pairs deterministically across all primary tables.

    Skips tables with drops (matching the raw CSV to the DB by index isn't
    safe), tables with no `db_rows` in the manifest, and tables whose
    in_path file isn't on disk.
    """
    pool: list[tuple[PrimaryTable, int]] = []
    for t in enumerate_primary_tables():
        entry = manifest_entry_for(t)
        if entry is None:
            continue
        sidecar = load_sidecar(t)
        if sidecar is not None and sidecar_drop_total(sidecar) > 0:
            continue
        if not t.payload_in_path.exists():
            continue
        n = entry.get("db_rows")
        if not isinstance(n, int) or n <= 0:
            continue
        # Pick a couple of rows per table proportional to size; cap at 4 so
        # one big table doesn't dominate the sample.
        per_table = min(4, max(1, n // 5000))
        for _ in range(per_table):
            pool.append((t, GENE_RNG.randrange(n)))

    GENE_RNG.shuffle(pool)
    return pool[:num_samples]


_SAMPLED = _sample_rows(SAMPLE_SIZE)


# ---------------------------------------------------------------------------
# 1. cleaned/raw → DB invariant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("table", "row_idx"),
    _SAMPLED,
    ids=[f"{t.dataset}/{t.table_name}#{i}" for t, i in _SAMPLED],
)
def test_in_path_row_matches_db(
    table: PrimaryTable, row_idx: int, db: sqlite3.Connection
) -> None:
    """The in_path CSV row at `row_idx` must equal the DB row `id == row_idx`."""
    df = _read_csv(table.dataset, table.in_path_name, table.separator)
    if df is None:
        pytest.skip(f"in_path {table.in_path_name} not on disk")
    if row_idx >= len(df):
        pytest.skip(f"sampled idx {row_idx} >= len(csv)={len(df)}")

    csv_row = df.iloc[row_idx]
    db_row = db.execute(
        f"SELECT * FROM {table.table_name} WHERE id = ?", (row_idx,)
    ).fetchone()
    assert db_row is not None, f"no DB row with id={row_idx} in {table.table_name}"
    db_keys = set(db_row.keys())

    mismatches: list[str] = []
    for col in df.columns:
        db_col = _normalize_col(col)
        if db_col not in db_keys:
            # CSV has a column the DB lacks — usually because load-db's
            # column-merge dropped a duplicate. Not our concern here.
            continue
        csv_val: Any = csv_row[col]
        db_val: Any = db_row[db_col]

        # CSV reads come back as strings (we passed dtype=str); the DB
        # carries typed values. Try a numeric coerce when the DB cell is
        # numeric, otherwise compare as strings — `_values_close` handles
        # missing-value sentinels uniformly.
        if isinstance(db_val, (int, float)) and not isinstance(db_val, bool):
            try:
                csv_num: Any = float(csv_val) if not _is_missing(csv_val) else math.nan
            except (TypeError, ValueError):
                csv_num = csv_val  # fall through to string compare in _values_close
            if not _values_close(csv_num, db_val):
                mismatches.append(f"{col!r}: csv={csv_val!r} db={db_val!r}")
        else:
            if not _values_close(csv_val, db_val):
                mismatches.append(f"{col!r}: csv={csv_val!r} db={db_val!r}")

    assert not mismatches, (
        f"{table.table_name}#id={row_idx}: {len(mismatches)} cell mismatch(es): "
        + "; ".join(mismatches[:5])
        + (f"; +{len(mismatches) - 5} more" if len(mismatches) > 5 else "")
    )


# ---------------------------------------------------------------------------
# 2. raw → cleaned round-trip (only when row indices line up)
# ---------------------------------------------------------------------------

def _raw_cleaned_pairs(num_samples: int) -> list[tuple[PrimaryTable, int]]:
    pool: list[tuple[PrimaryTable, int]] = []
    rng = random.Random(SEED + 1)
    for t in enumerate_primary_tables():
        entry = manifest_entry_for(t)
        if entry is None:
            continue
        if not entry.get("pipeline_used"):
            continue  # raw == in_path; the test above already covered it.
        sidecar = load_sidecar(t)
        if not _has_only_count_neutral_steps(sidecar):
            continue
        raw_name = entry.get("raw_file")
        cleaned_name = entry.get("cleaned_file") or t.in_path_name
        if not raw_name or not cleaned_name:
            continue
        raw_p = payload_dataset_dir(t.dataset) / raw_name
        cleaned_p = payload_dataset_dir(t.dataset) / cleaned_name
        if not (raw_p.exists() and cleaned_p.exists()):
            continue
        n = entry.get("raw_rows")
        if not isinstance(n, int) or n <= 0:
            continue
        per_table = min(3, max(1, n // 10000))
        for _ in range(per_table):
            pool.append((t, rng.randrange(n)))
    rng.shuffle(pool)
    return pool[:num_samples]


_RAW_CLEAN = _raw_cleaned_pairs(SAMPLE_SIZE)


@pytest.mark.parametrize(
    ("table", "row_idx"),
    _RAW_CLEAN,
    ids=[f"{t.dataset}/{t.table_name}#{i}" for t, i in _RAW_CLEAN],
)
def test_raw_to_cleaned_roundtrip(table: PrimaryTable, row_idx: int) -> None:
    """For tables with no row drops, raw[i] and cleaned[i] agree on every
    non-gene column, and `<gene_col>_raw` in the cleaned CSV preserves the
    raw gene value exactly.
    """
    entry = manifest_entry_for(table)
    assert entry is not None  # already filtered upstream
    raw_df = _read_csv(table.dataset, entry["raw_file"], table.separator)
    cleaned_df = _read_csv(
        table.dataset, entry.get("cleaned_file") or table.in_path_name, table.separator
    )
    assert raw_df is not None and cleaned_df is not None
    if row_idx >= min(len(raw_df), len(cleaned_df)):
        pytest.skip("sampled idx exceeds either file's length")

    raw_row = raw_df.iloc[row_idx]
    cleaned_row = cleaned_df.iloc[row_idx]

    # A column is "resolution-affected" iff `clean_gene_column` ran on it
    # — detected by the presence of a `<col>_raw` companion in the
    # cleaned CSV. That's both the columns listed in config.yaml's
    # `gene_mappings` AND any extra columns the wrangler ran clean_gene
    # on in preprocess.py (e.g. sfari_human_genes resolves `ensembl-id`).
    cleaned_cols = set(cleaned_df.columns)
    for col in raw_df.columns:
        if col not in cleaned_cols:
            continue  # column was renamed/dropped, not our concern here
        raw_v = raw_row[col]
        clean_v = cleaned_row[col]
        raw_companion = f"{col}_raw"
        if raw_companion in cleaned_cols:
            # Cleaned column was rewritten by clean_gene_column. The
            # original value is in the `_raw` companion.
            preserved = cleaned_df.iloc[row_idx][raw_companion]
            assert _values_close(preserved, raw_v), (
                f"{table.table_name}#{row_idx}: gene column {col!r} not "
                f"preserved in cleaned CSV's {raw_companion!r} "
                f"(raw={raw_v!r}, cleaned_raw={preserved!r})"
            )
            continue
        # Non-resolved column — values must match.
        assert _values_close(raw_v, clean_v), (
            f"{table.table_name}#{row_idx}: column {col!r} mutated between "
            f"raw and cleaned (raw={raw_v!r}, cleaned={clean_v!r})"
        )
