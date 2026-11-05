"""Input fingerprint for the meta-analysis, so an unchanged rerun can be skipped.

`sspsygene meta-analysis` used to rebuild whenever the dataset DB's build UUID
changed — i.e. after every `load-db`, even one that touched no
differential-expression table. The fingerprint here describes everything the
meta DB's contents are a function of; when it matches the one stored in the
existing meta DB, that file is still correct for the new dataset DB and only
needs its `source_build_uuid` re-stamped.

A false "unchanged" silently serves wrong rankings, so the fingerprint errs on
the side of "changed". It has two halves:

1. **Per-table content hash, computed by `load-db`** (`table_content_hash`,
   stored in `data_tables.meta_input_hash`). Hashes exactly what the
   meta-analysis later reads from a data table and its link tables: the `id`
   column, every configured p-value column and the effect column (exact bytes
   for numeric columns), and every link table's `(central_gene_id, id)` pairs
   plus its name / gene column / direction. It hashes the loaded *output*, not
   the input file, so any change in preprocessing, gene resolution or loader
   code that alters what lands in the table is caught. Computed from the
   in-memory DataFrame, so it costs no extra scan of the DB.

2. **Everything else, computed by `meta-analysis`** (`compute_fingerprint`):
   - the exact source-table catalog the run would use (`data_tables` rows after
     the assay / `meta_analysis:` / prod-destination filters — names, p-value /
     effect columns, link-table specs, assay / condition / organism keys);
   - the configured `metaAnalysisAssays`;
   - gene identity for every gene those link tables reference: `(id, kind,
     human_symbol, hgnc_id)` from `central_gene`. central_gene ids are
     positional, and the meta DB stores bare ids that the web app joins back to
     the dataset DB's central_gene, so a gene-table change re-maps them;
   - the HGNC / NIMH / TF reference files' bytes (gene flags);
   - a code version: the bytes of every module in this package, the R script,
     the meta-DB orchestration in sq_load, and `META_SCHEMA_VERSION`;
   - `no_index` (it changes the shape of the output DB).

A source DB that predates the `meta_input_hash` column, or any table with a
NULL hash, yields no fingerprint — which always means "rebuild".
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from processing.types.link_table import LinkTable

# Bump to invalidate every stored fingerprint when the fingerprint's own
# definition changes in a way the hashed sources would not reveal.
FINGERPRINT_VERSION = "1"

_PACKAGE_DIR = Path(__file__).parent
_R_SCRIPT = _PACKAGE_DIR.parent / "r" / "compute_combined.R"


def _frame(h: "hashlib._Hash", tag: str, data: bytes) -> None:
    """Length-prefixed write, so adjacent fields can't run into each other."""
    tag_b = tag.encode()
    h.update(len(tag_b).to_bytes(8, "little"))
    h.update(tag_b)
    h.update(len(data).to_bytes(8, "little"))
    h.update(data)


def _series_bytes(series: pd.Series) -> bytes:
    """Exact, deterministic bytes for one column's values.

    Numeric / bool columns hash their raw buffer (bit-exact, so any change to a
    p-value is visible). Anything else — object columns that mix strings and
    numbers, nullable extension dtypes — takes a slow but exact per-value repr
    path that also records each value's type, since SQLite compares an INTEGER
    1 and a TEXT '1' differently."""
    arr = series.to_numpy()
    if arr.dtype.kind in "biuf":
        return arr.dtype.str.encode() + b"|" + np.ascontiguousarray(arr).tobytes()
    return "\x1f".join(
        f"{type(v).__name__}:{v!r}" for v in arr.tolist()
    ).encode()


def _wanted_columns(
    pvalue_column: str | None, effect_column: str | None
) -> list[str]:
    cols = ["id"]
    for c in (pvalue_column or "").split(","):
        if c.strip():
            cols.append(c.strip())
    if effect_column:
        cols.append(effect_column)
    return cols


def table_content_hash(
    data: pd.DataFrame,
    link_tables: Sequence["LinkTable"],
    pvalue_column: str | None,
    effect_column: str | None,
) -> str | None:
    """Content key for everything the meta-analysis reads from one data table.

    None for tables with no p-value column — the meta-analysis never reads
    them. Column lookup is case-insensitive because SQLite's is: `t.PValue`
    resolves to a column stored as `pvalue`, so every case-variant match is
    hashed."""
    if not pvalue_column:
        return None
    h = hashlib.sha256()
    _frame(h, "version", FINGERPRINT_VERSION.encode())
    _frame(h, "nrows", str(len(data)).encode())
    by_lower: dict[str, list[str]] = {}
    for col in data.columns:
        by_lower.setdefault(str(col).lower(), []).append(str(col))
    for wanted in _wanted_columns(pvalue_column, effect_column):
        matches = by_lower.get(wanted.lower(), [])
        _frame(h, "col", wanted.encode())
        if not matches:
            _frame(h, "absent", b"")
            continue
        for actual in matches:
            _frame(h, "actual", actual.encode())
            _frame(h, "values", _series_bytes(data[actual]))
    for lt in link_tables:
        _frame(
            h,
            "link",
            f"{lt.link_table_name}:{lt.gene_column_name}:"
            f"{lt.perturbed_or_target}".encode(),
        )
        # Exactly what LinkTable.write_to_sqlite stores: non-null gene ids,
        # deduplicated (gene, row) pairs — hashed in a canonical sorted order.
        # Built from Python ints (not via a DataFrame, whose None handling
        # would round-trip the hash-derived ids through float64).
        pairs = np.array(
            [
                (int(gene_id), int(row_id))
                for row_id, gene_id in lt.central_gene_table_links
                if gene_id is not None
            ],
            dtype=np.int64,
        ).reshape(-1, 2)
        if len(pairs):
            pairs = np.unique(pairs, axis=0)
        _frame(h, "pairs", np.ascontiguousarray(pairs).tobytes())
    return h.hexdigest()


def _file_digest(path: Path | None) -> str:
    if path is None or not path.exists():
        return "absent"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def code_version() -> str:
    """Hash of the code that turns the inputs into the meta DB."""
    from processing import sq_load  # lazy: sq_load imports this package

    h = hashlib.sha256()
    _frame(h, "fingerprint_version", FINGERPRINT_VERSION.encode())
    _frame(h, "meta_schema_version", sq_load.META_SCHEMA_VERSION.encode())
    for path in sorted(_PACKAGE_DIR.glob("*.py")):
        _frame(h, path.name, path.read_bytes())
    _frame(h, _R_SCRIPT.name, _R_SCRIPT.read_bytes())
    for fn in (sq_load.run_meta_analysis, sq_load._write_meta_analysis_info):
        _frame(h, fn.__name__, inspect.getsource(fn).encode())
    return h.hexdigest()


def _has_column(conn: sqlite3.Connection, schema: str, table: str, col: str) -> bool:
    return any(
        r[1] == col
        for r in conn.execute(f"PRAGMA {schema}.table_info({table})").fetchall()
    )


def _link_table_names(link_tables_raw: str | None) -> list[str]:
    from processing.sql_utils import sanitize_identifier

    out: list[str] = []
    for entry in (link_tables_raw or "").split(","):
        parts = entry.strip().split(":")
        if len(parts) >= 3:
            out.append(sanitize_identifier(parts[1]))
    return out


def _gene_identity_digest(
    conn: sqlite3.Connection, src_schema: str, link_tables: Iterable[str]
) -> str:
    """Digest of `(id, kind, human_symbol, hgnc_id)` for every central gene the
    meta tables' link tables reference. A link-table id with no central_gene row
    contributes `(id, None, None, None)`, so a gene appearing later is seen."""
    names = sorted(set(link_tables))
    h = hashlib.sha256()
    if not names:
        return h.hexdigest()
    union = " UNION ".join(
        f"SELECT central_gene_id AS gid FROM {src_schema}.[{n}]" for n in names
    )
    rows = conn.execute(
        f"SELECT u.gid, cg.kind, cg.human_symbol, cg.hgnc_id "
        f"FROM ({union}) u LEFT JOIN {src_schema}.central_gene cg "
        f"ON cg.id = u.gid ORDER BY u.gid"
    )
    for row in rows:
        h.update(repr(tuple(row)).encode())
        h.update(b"\n")
    return h.hexdigest()


def compute_fingerprint(
    conn: sqlite3.Connection,
    source_tables: Sequence[Sequence[Any]],
    *,
    src_schema: str,
    deg_assays: set[str] | None,
    hgnc_path: Path | None,
    nimh_csv_path: Path | None,
    tf_list_path: Path | None,
    no_index: bool,
) -> dict[str, Any] | None:
    """Fingerprint components for a meta-analysis over `source_tables`.

    `source_tables` must be exactly the catalog `MetaAnalysisRun` would use
    (`MetaAnalysisRun._load_source_tables()`), so the fingerprint and the build
    agree on which tables count. Returns None when the source DB cannot be
    fingerprinted (no `meta_input_hash` column, or a table without one) —
    callers must treat that as "changed"."""
    if not _has_column(conn, src_schema, "data_tables", "meta_input_hash"):
        return None
    hashes = dict(
        conn.execute(
            f"SELECT table_name, meta_input_hash FROM {src_schema}.data_tables"
        ).fetchall()
    )
    tables: dict[str, Any] = {}
    link_names: list[str] = []
    for row in sorted(source_tables, key=lambda r: r[0]):
        content = hashes.get(row[0])
        if not content:
            return None
        tables[row[0]] = {"catalog": list(row), "content": content}
        link_names.extend(_link_table_names(row[2]))
    return {
        "fingerprint_version": FINGERPRINT_VERSION,
        "code": code_version(),
        "assays": sorted(deg_assays) if deg_assays is not None else None,
        "no_index": bool(no_index),
        "tables": tables,
        "genes": _gene_identity_digest(conn, src_schema, link_names),
        "hgnc": _file_digest(hgnc_path),
        "nimh": _file_digest(nimh_csv_path),
        "tf_list": _file_digest(tf_list_path),
    }


def fingerprint_digest(components: dict[str, Any]) -> str:
    """Single comparable digest over the canonical JSON of the components."""
    blob = json.dumps(components, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def describe_changes(
    old: dict[str, Any] | None, new: dict[str, Any]
) -> list[str]:
    """Human-readable list of which components differ, for the log line."""
    if old is None:
        return ["no stored fingerprint"]
    out: list[str] = []
    for key in sorted(set(old) | set(new)):
        if key == "tables":
            continue
        if old.get(key) != new.get(key):
            out.append(key)
    old_t = old.get("tables") or {}
    new_t = new.get("tables") or {}
    added = sorted(set(new_t) - set(old_t))
    removed = sorted(set(old_t) - set(new_t))
    changed = sorted(
        t for t in set(old_t) & set(new_t) if old_t[t] != new_t[t]
    )
    if added:
        out.append(f"tables added: {', '.join(added)}")
    if removed:
        out.append(f"tables removed: {', '.join(removed)}")
    if changed:
        out.append(f"tables changed: {', '.join(changed)}")
    return out
