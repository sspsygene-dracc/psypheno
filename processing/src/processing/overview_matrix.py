"""Materialization of the collated cross-modality overview matrix (#222).

`/api/collated-matrix` used to compute the whole perturbed-gene × modality
aggregation live on every request (~6.8 s), and the #222 RNA-expression
expansion would have added another ~5.6 s on top. Both halves are pure,
deterministic SQL over the dataset DB, so they are precomputed here during
`load-db` — the same reasoning that moved the combined p-values into their own
build in #176 — and the API becomes a cheap indexed read.

Two kinds of column are materialized:

**Status columns** (the original #212 matrix). One column per modality; the cell
is a status glyph aggregated over every `overview_matrix`-labeled table whose
`assay` maps to that modality:

    nSig     = rows where any pvalue/fdr column < 0.05
    nData    = rows where any pvalue/fdr column IS NOT NULL
    nAssayed = joined rows (gene present in the perturbed link table)

with precedence ``significant`` > ``data`` > ``assayed_null`` > ``none``.
Controls (``central_gene.kind = 'control'``) are excluded. This is a port of the
query the API ran live; it must stay behaviourally identical.

**Expanded columns** (new in #222). A table flagged `overview_matrix_expand`
turns its modality into a p-value heatmap with one sub-column per measured
(target) gene. A target qualifies when it is FDR-significant across at least
`min_groups` distinct values of the table's *perturbed* gene column — for the ASD
organoid table those values are the CNV regions, which is the honest unit because
every member gene of a region shares the identical DE rows (#221). Groups that
resolve to no perturbed gene don't count (that table's idiopathic-ASD cohort has
no molecular diagnosis, so it contributes no cells either). Each cell carries
``-log10(min raw p)`` for that (perturbed gene, target gene) pair, clamped to
``[1, 20]``.

Row ordering is deliberately *not* materialized: the API sorts genes with
JavaScript's ``localeCompare``, which Python cannot reproduce byte-for-byte.
"""

import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import click

from processing.combined_pvalues.collection import parse_link_tables_for_direction
from processing.my_logger import get_sspsygene_logger
from processing.sql_utils import sanitize_identifier
from processing.types.table_to_process_config import normalize_column_name


SCHEMA_VERSION = "2"

# Cell-status precedence, strongest first.
STATUS_SIGNIFICANT = "significant"
STATUS_DATA = "data"
STATUS_ASSAYED_NULL = "assayed_null"

# -log10(p) clamp for expanded heatmap cells. The lower bound keeps every
# present cell visible against "no data"; the upper bound stops a single
# p ~ 1e-49 row (they exist) from owning the whole color ramp.
NEG_LOG_P_MIN = 1.0
NEG_LOG_P_MAX = 20.0

# Response-side key prefix for an expanded modality's sub-columns, e.g.
# `expr:<table>:SHANK3`. Stored in the DB so the web API doesn't hardcode it.
_COLUMN_PREFIXES = {
    "expression": "expr",
    "perturb_seq": "ps",
    "perturb_fish": "pf",
}

# A target gene is an expanded column only if it is FDR-significant across at
# least this many distinct perturbed-side groups (CNV regions for the organoid
# table, perturbed genes elsewhere). Fixed floor — the API/UI tunes *how many*
# columns per dataset to show, not this eligibility bar.
ELIGIBILITY_MIN_GROUPS = 2

# Only the top-M most-convergent columns per (modality, source table) are
# materialized. M is the largest "columns per dataset" the UI offers, so nothing
# selectable is ever missing while the DB stays small even for the dense CRISPR
# screens (SCZ arrayed alone has ~8.5k eligible columns).
MATERIALIZE_TOP_M = 200

_TABLES = (
    "overview_matrix_genes",
    "overview_matrix_status_cells",
    "overview_matrix_expansions",
    "overview_matrix_expanded_columns",
    "overview_matrix_expanded_cells",
    "overview_matrix_info",
)


def _create_schema(conn: sqlite3.Connection) -> None:
    for table in _TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(
        """CREATE TABLE overview_matrix_genes (
        central_gene_id INTEGER PRIMARY KEY,
        human_symbol TEXT)"""
    )
    # Only non-"none" cells are stored; the API fills the gaps.
    conn.execute(
        """CREATE TABLE overview_matrix_status_cells (
        central_gene_id INTEGER NOT NULL,
        modality_key TEXT NOT NULL,
        status TEXT NOT NULL,
        count INTEGER NOT NULL,
        table_names TEXT NOT NULL,
        PRIMARY KEY (central_gene_id, modality_key)) WITHOUT ROWID"""
    )
    conn.execute(
        """CREATE TABLE overview_matrix_expansions (
        modality_key TEXT PRIMARY KEY,
        column_prefix TEXT NOT NULL,
        source_tables TEXT NOT NULL,
        n_columns_total INTEGER NOT NULL)"""
    )
    # An expanded modality can fan out several source datasets (perturb-seq has
    # six); `source_table` keeps a target gene from different datasets in
    # distinct columns and lets the API group + label them by dataset.
    conn.execute(
        """CREATE TABLE overview_matrix_expanded_columns (
        modality_key TEXT NOT NULL,
        source_table TEXT NOT NULL,
        source_label TEXT,
        column_value TEXT NOT NULL,
        n_sig_groups INTEGER NOT NULL,
        min_p REAL NOT NULL,
        sort_rank INTEGER NOT NULL,
        PRIMARY KEY (modality_key, source_table, column_value)) WITHOUT ROWID"""
    )
    # Clustered by column, not by gene: the read path always selects a set of
    # qualifying columns and wants every gene's value for each, so a
    # column-major key turns the whole fetch into one contiguous range scan per
    # column instead of a scan of the full cell table.
    conn.execute(
        """CREATE TABLE overview_matrix_expanded_cells (
        modality_key TEXT NOT NULL,
        source_table TEXT NOT NULL,
        column_value TEXT NOT NULL,
        central_gene_id INTEGER NOT NULL,
        neg_log_p REAL NOT NULL,
        PRIMARY KEY (modality_key, source_table, column_value, central_gene_id))
        WITHOUT ROWID"""
    )
    conn.execute(
        """CREATE TABLE overview_matrix_info (
        key TEXT PRIMARY KEY,
        value TEXT)"""
    )


def _load_modalities(
    conn: sqlite3.Connection, src_schema: str
) -> tuple[list[str], dict[str, list[str]]]:
    """Return (ordered modality keys, assay-type key → modality keys)."""
    rows = conn.execute(
        f"SELECT key, assay_types FROM {src_schema}.modalities ORDER BY sort_order ASC"
    ).fetchall()
    keys = [row[0] for row in rows]
    assay_to_modalities: dict[str, list[str]] = defaultdict(list)
    for key, assay_types_raw in rows:
        try:
            assay_types = json.loads(assay_types_raw or "[]")
        except (TypeError, ValueError):
            assay_types = []
        for assay in assay_types:
            assay_to_modalities[assay].append(key)
    return keys, dict(assay_to_modalities)


def _split_columns(raw: str | None) -> list[str]:
    """Split a comma-separated column list, dropping unusable identifiers.

    Mirrors the API's tolerance: a single malformed entry is skipped rather
    than aborting the whole build.
    """
    out: list[str] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(sanitize_identifier(part))
        except ValueError:
            continue
    return out


def _modality_keys_for(
    assay_raw: str | None, assay_to_modalities: dict[str, list[str]]
) -> list[str]:
    keys: list[str] = []
    for assay in (assay_raw or "").split(","):
        assay = assay.strip()
        if not assay:
            continue
        for key in assay_to_modalities.get(assay, []):
            if key not in keys:
                keys.append(key)
    return keys


def _table_columns(conn: sqlite3.Connection, table: str, src_schema: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA {src_schema}.table_info({table})")}


def _materialize_status_cells(
    conn: sqlite3.Connection,
    source_rows: list[tuple[Any, ...]],
    assay_to_modalities: dict[str, list[str]],
    src_schema: str,
) -> None:
    """Write `overview_matrix_status_cells` for every labeled source table."""
    log = get_sspsygene_logger()
    # (gene id, modality key) -> [nSig, nData, nAssayed, {table names}]
    accum: dict[tuple[int, str], list[Any]] = {}
    universe: set[int] = set()

    for table_name, assay, pvalue_column, fdr_column, link_tables_raw, _expand in (
        source_rows
    ):
        link_tables = parse_link_tables_for_direction(link_tables_raw or "", "perturbed")
        if not link_tables:
            continue
        modality_keys = _modality_keys_for(assay, assay_to_modalities)
        if not modality_keys:
            # A labeled table whose assay maps to no modality is a
            # misconfiguration; skip it rather than emit orphan cells.
            log.warning(
                "overview matrix: table %s (assay %r) maps to no modality, skipping",
                table_name,
                assay,
            )
            continue
        try:
            base_table = sanitize_identifier(table_name)
        except ValueError:
            continue

        stat_cols = _split_columns(pvalue_column) + _split_columns(fdr_column)
        # A table with no usable stat column can only ever contribute
        # "assayed_null" — the literal 0 predicates say so explicitly.
        data_predicate = (
            " OR ".join(f"t.{col} IS NOT NULL" for col in stat_cols)
            if stat_cols
            else "0"
        )
        sig_predicate = (
            " OR ".join(
                f"(t.{col} IS NOT NULL AND t.{col} < 0.05)" for col in stat_cols
            )
            if stat_cols
            else "0"
        )

        for link_table in link_tables:
            rows = conn.execute(
                f"""SELECT lt.central_gene_id,
                           COUNT(*),
                           SUM(CASE WHEN ({data_predicate}) THEN 1 ELSE 0 END),
                           SUM(CASE WHEN ({sig_predicate}) THEN 1 ELSE 0 END)
                      FROM {src_schema}.{base_table} t
                      JOIN {src_schema}.{link_table} lt ON t.id = lt.id
                      JOIN {src_schema}.central_gene cg ON cg.id = lt.central_gene_id
                     WHERE cg.kind != 'control'
                     GROUP BY lt.central_gene_id"""
            ).fetchall()
            for gene_id, n_assayed, n_data, n_sig in rows:
                universe.add(gene_id)
                # One assay can map to several modalities (perturb-FISH data is
                # also perturb-seq data); it contributes to each of them.
                for modality_key in modality_keys:
                    entry = accum.setdefault(
                        (gene_id, modality_key), [0, 0, 0, set()]
                    )
                    entry[0] += n_sig or 0
                    entry[1] += n_data or 0
                    entry[2] += n_assayed or 0
                    entry[3].add(table_name)

    cell_rows: list[tuple[int, str, str, int, str]] = []
    for (gene_id, modality_key), (n_sig, n_data, n_assayed, table_names) in (
        accum.items()
    ):
        if n_sig > 0:
            status, count = STATUS_SIGNIFICANT, n_sig
        elif n_data > 0:
            status, count = STATUS_DATA, n_data
        elif n_assayed > 0:
            status, count = STATUS_ASSAYED_NULL, n_assayed
        else:
            continue
        cell_rows.append(
            (
                gene_id,
                modality_key,
                status,
                count,
                json.dumps(sorted(table_names)),
            )
        )
    conn.executemany(
        "INSERT INTO overview_matrix_status_cells "
        "(central_gene_id, modality_key, status, count, table_names) "
        "VALUES (?, ?, ?, ?, ?)",
        cell_rows,
    )
    click.echo(
        f"  Overview matrix: {len(cell_rows)} status cells "
        f"over {len(universe)} perturbed genes"
    )


def _group_to_genes(
    conn: sqlite3.Connection,
    base_table: str,
    link_table: str,
    group_expr: str,
    src_schema: str,
) -> dict[Any, list[int]]:
    """Map each distinct perturbed-column value to its central gene ids.

    Rows sharing a perturbed-column value always resolve to the same gene set —
    the link rows are generated per value — so one representative row id per
    distinct value is enough, and the 11M-row link table is scanned once with a
    tiny `IN` filter instead of being joined row-by-row. The invariant is
    asserted against the link table's row count; on any mismatch we fall back to
    the exact (slower) DISTINCT join.
    """
    log = get_sspsygene_logger()
    controls = {
        row[0]
        for row in conn.execute(
            f"SELECT id FROM {src_schema}.central_gene WHERE kind = 'control'"
        )
    }
    reps = conn.execute(
        f"SELECT {group_expr}, MIN(id), COUNT(*) "
        f"FROM {src_schema}.{base_table} GROUP BY {group_expr}"
    ).fetchall()
    rep_id_to_group = {rep_id: group for group, rep_id, _ in reps}
    rows_per_group = {group: n_rows for group, _, n_rows in reps}

    placeholders = ",".join("?" for _ in rep_id_to_group)
    # Controls stay in `full_mapping` (they occupy link rows too, so dropping
    # them would break the row-count check) and are filtered out at the end.
    full_mapping: dict[Any, list[int]] = {group: [] for group in rows_per_group}
    if rep_id_to_group:
        for row_id, gene_id in conn.execute(
            f"""SELECT id, central_gene_id FROM {src_schema}.{link_table}
                 WHERE id IN ({placeholders})""",
            list(rep_id_to_group),
        ):
            full_mapping[rep_id_to_group[row_id]].append(gene_id)

    expected = sum(
        rows_per_group[group] * len(gene_ids) for group, gene_ids in full_mapping.items()
    )
    (actual,) = conn.execute(
        f"SELECT COUNT(*) FROM {src_schema}.{link_table}"
    ).fetchone()
    if expected == actual:
        return {
            group: [gene_id for gene_id in gene_ids if gene_id not in controls]
            for group, gene_ids in full_mapping.items()
        }

    # The per-value invariant doesn't hold for this table — redo it exactly.
    log.warning(
        "overview matrix: %s link-row count %d != expected %d from the "
        "representative-row shortcut; falling back to the exact join",
        link_table,
        actual,
        expected,
    )
    mapping: dict[Any, list[int]] = {group: [] for group in rows_per_group}
    for group, gene_id in conn.execute(
        f"""SELECT DISTINCT {group_expr}, lt.central_gene_id
              FROM {src_schema}.{base_table} t
              JOIN {src_schema}.{link_table} lt ON lt.id = t.id
              JOIN {src_schema}.central_gene cg ON cg.id = lt.central_gene_id
             WHERE cg.kind != 'control'"""
    ):
        mapping.setdefault(group, []).append(gene_id)
    return mapping


def _materialize_expansion(
    conn: sqlite3.Connection,
    *,
    modality_key: str,
    table_name: str,
    source_label: str | None,
    pvalue_column: str | None,
    fdr_column: str | None,
    link_tables_raw: str | None,
    min_groups: int,
    src_schema: str,
) -> int:
    """Materialize one expanded (modality, source table). Returns column count.

    Columns are the measured *target* genes that are FDR-significant across at
    least `min_groups` distinct perturbed-side groups; only the top
    MATERIALIZE_TOP_M most-convergent are kept (the API serves the top K <= M per
    dataset). Each cell holds -log10(most significant p) per (perturbed gene,
    target). Rows are tagged with `table_name` so several datasets can share a
    modality without their columns colliding.
    """
    log = get_sspsygene_logger()
    base_table = sanitize_identifier(table_name)
    perturbed_links = parse_link_tables_for_direction(link_tables_raw or "", "perturbed")
    if not perturbed_links:
        log.warning(
            "overview matrix: %s is flagged for expansion but has no perturbed "
            "link table, skipping",
            table_name,
        )
        return 0
    link_table = perturbed_links[0]

    # The sub-column axis and the significance-group axis are the *source
    # columns* of the target / perturbed link entries, normalized the same way
    # the loader normalizes column names.
    columns = _table_columns(conn, base_table, src_schema)
    source_columns: dict[str, str | None] = {"target": None, "perturbed": None}
    for entry in (link_tables_raw or "").split(","):
        parts = entry.strip().split(":")
        if len(parts) < 3:
            continue
        candidate = normalize_column_name(parts[0])
        if parts[2] in source_columns and candidate in columns:
            source_columns[parts[2]] = candidate

    target_column = source_columns["target"]
    if target_column is None:
        log.warning(
            "overview matrix: %s has no usable target column, skipping expansion",
            table_name,
        )
        return 0
    # An implicit (constant_value) perturbation has no per-row column; the whole
    # table is then a single significance group.
    group_expr = source_columns["perturbed"] or "''"

    pvalue_cols = _split_columns(pvalue_column)
    fdr_cols = _split_columns(fdr_column)
    # Colour by the raw p when present; a table with only an FDR (perturb-FISH
    # ships just a qval) uses that FDR as the p. Significance selection uses the
    # FDR when available, else the same single column.
    p_col = pvalue_cols[0] if pvalue_cols else (fdr_cols[0] if fdr_cols else None)
    fdr_col = fdr_cols[0] if fdr_cols else (pvalue_cols[0] if pvalue_cols else None)
    if p_col is None or fdr_col is None:
        log.warning(
            "overview matrix: %s lacks a usable pvalue/fdr column, skipping expansion",
            table_name,
        )
        return 0

    group_genes = _group_to_genes(conn, base_table, link_table, group_expr, src_schema)

    # Per (group, target): the most significant raw p and the most significant
    # FDR. MIN(fdr) < 0.05 is exactly "at least one significant row here".
    per_group = conn.execute(
        f"""SELECT {group_expr}, {target_column}, MIN({p_col}), MIN({fdr_col})
              FROM {src_schema}.{base_table}
             WHERE {target_column} IS NOT NULL AND {target_column} != ''
             GROUP BY 1, 2"""
    ).fetchall()

    # Only groups that resolve to at least one perturbed central gene can
    # select a column. The organoid table's idiopathic-ASD cohort has no
    # molecular diagnosis and therefore no perturbed gene, so it contributes no
    # matrix cells either — letting it qualify a column would produce a column
    # that renders completely empty.
    n_sig_by_target: dict[str, int] = defaultdict(int)
    min_p_by_target: dict[str, float] = {}
    for group, target, min_p, min_fdr in per_group:
        if min_p is None or not group_genes.get(group):
            continue
        if min_fdr is not None and min_fdr < 0.05:
            n_sig_by_target[target] += 1
        current = min_p_by_target.get(target)
        if current is None or min_p < current:
            min_p_by_target[target] = min_p

    qualifying = {
        target: n_sig
        for target, n_sig in n_sig_by_target.items()
        if n_sig >= min_groups and target in min_p_by_target
    }
    if not qualifying:
        return 0

    # Most-convergent first (then strongest single p, then name), capped at the
    # per-dataset materialization limit. `sort_rank` is 0-based within this
    # (modality, source table), so the API's `LIMIT K` takes the top K.
    ordered = sorted(
        qualifying, key=lambda t: (-qualifying[t], min_p_by_target[t], t)
    )[:MATERIALIZE_TOP_M]
    kept = set(ordered)
    conn.executemany(
        "INSERT INTO overview_matrix_expanded_columns "
        "(modality_key, source_table, source_label, column_value, n_sig_groups, "
        " min_p, sort_rank) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                modality_key,
                table_name,
                source_label,
                target,
                qualifying[target],
                min_p_by_target[target],
                rank,
            )
            for rank, target in enumerate(ordered)
        ],
    )

    # Cells: expand each (group, target) across the group's central genes,
    # keeping the most significant p per (gene, target). A gene can sit in two
    # groups (SHANK3 is both its own perturbation and a member of the 22q13
    # region), hence the min rather than an overwrite. Only the kept (top-M)
    # columns get cells.
    cells: dict[tuple[int, str], float] = {}
    for group, target, min_p, _min_fdr in per_group:
        if min_p is None or target not in kept:
            continue
        for gene_id in group_genes.get(group, ()):
            key = (gene_id, target)
            current = cells.get(key)
            if current is None or min_p < current:
                cells[key] = min_p
    conn.executemany(
        "INSERT INTO overview_matrix_expanded_cells "
        "(modality_key, source_table, column_value, central_gene_id, neg_log_p) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (modality_key, table_name, target, gene_id, _neg_log_p(min_p))
            for (gene_id, target), min_p in cells.items()
        ],
    )
    click.echo(
        f"  Overview matrix: '{modality_key}' / {table_name} → "
        f"{len(ordered)} columns / {len(cells)} cells "
        f"(≥ {min_groups} sig group(s), top {MATERIALIZE_TOP_M})"
    )
    return len(ordered)


def _neg_log_p(p: float) -> float:
    """-log10(p), clamped to [1, 20]. p <= 0 (underflow to zero) maps to the top.

    Rounded to 3 decimals: this is a color-ramp coordinate, not an analysis
    value, and full float64 repr would add ~13 bytes to each of the tens of
    thousands of cells in an /api/collated-matrix response.
    """
    if p <= 0:
        return NEG_LOG_P_MAX
    return round(min(max(-math.log10(p), NEG_LOG_P_MIN), NEG_LOG_P_MAX), 3)


def materialize_overview_matrix(
    conn: sqlite3.Connection,
    *,
    no_index: bool = False,
    min_groups: int = ELIGIBILITY_MIN_GROUPS,
    src_schema: str = "main",
) -> None:
    """Precompute the overview matrix (#222).

    Writes the `overview_matrix_*` tables into `conn`'s main schema, reading the
    dataset tables (`modalities`, `data_tables`, `central_gene`, and each
    labeled source/link table) from `src_schema`. `run_overview_matrix` passes
    ``src_schema="src"`` with the dataset DB ATTACHed read-only, so the matrix
    lands in its own file; the in-process path (tests) leaves it ``"main"`` and
    everything is one DB.

    `min_groups` is the *eligibility floor*: a target gene becomes an expanded
    sub-column only when it is FDR-significant across at least this many distinct
    perturbed groups (default 2). Independently, at most `MATERIALIZE_TOP_M` of
    the most-convergent columns are kept per (modality, source table) — the API
    then serves the top K <= M per dataset.
    """
    min_groups = max(1, min_groups)
    _create_schema(conn)

    modality_keys, assay_to_modalities = _load_modalities(conn, src_schema)
    if not modality_keys:
        # No taxonomy (older globals.yaml) — leave the tables empty rather than
        # failing the build; the API degrades to an empty matrix.
        _write_info(conn, min_groups, [])
        conn.commit()
        return

    source_rows = conn.execute(
        f"""SELECT table_name, assay, pvalue_column, fdr_column, link_tables,
                   expand_in_overview_matrix, short_label
             FROM {src_schema}.data_tables
            WHERE include_in_overview_matrix = 1"""
    ).fetchall()

    # Status aggregation ignores the two trailing columns (expand flag, label).
    _materialize_status_cells(
        conn,
        [row[:6] for row in source_rows],
        assay_to_modalities,
        src_schema,
    )
    # Every joined row yields at least an "assayed_null" cell, so the status
    # cells already carry the full perturbed-gene universe. The status-cell
    # table lives in the write DB (unqualified); central_gene is read from src.
    conn.execute(
        f"""INSERT INTO overview_matrix_genes (central_gene_id, human_symbol)
           SELECT DISTINCT c.central_gene_id, cg.human_symbol
             FROM overview_matrix_status_cells c
             JOIN {src_schema}.central_gene cg ON cg.id = c.central_gene_id"""
    )

    expanded_source_tables: list[str] = []
    for (
        table_name,
        assay,
        pvalue_column,
        fdr_column,
        link_tables_raw,
        expand,
        short_label,
    ) in source_rows:
        if not expand:
            continue
        modality_keys_for_table = _modality_keys_for(assay, assay_to_modalities)
        if not modality_keys_for_table:
            continue
        # An expanded table drives exactly one section: its first modality.
        modality_key = modality_keys_for_table[0]
        n_columns = _materialize_expansion(
            conn,
            modality_key=modality_key,
            table_name=table_name,
            source_label=short_label,
            pvalue_column=pvalue_column,
            fdr_column=fdr_column,
            link_tables_raw=link_tables_raw,
            min_groups=min_groups,
            src_schema=src_schema,
        )
        if n_columns == 0:
            continue
        expanded_source_tables.append(table_name)
        conn.execute(
            "INSERT INTO overview_matrix_expansions "
            "(modality_key, column_prefix, source_tables, n_columns_total) "
            "VALUES (?, ?, ?, ?)"
            " ON CONFLICT(modality_key) DO UPDATE SET "
            " source_tables = source_tables || ',' || excluded.source_tables,"
            " n_columns_total = n_columns_total + excluded.n_columns_total",
            (
                modality_key,
                _COLUMN_PREFIXES.get(modality_key, modality_key),
                table_name,
                n_columns,
            ),
        )

    if not no_index:
        # The read path selects a (modality, source table) and walks its columns
        # in rank order (top K per dataset); the cells need no index because the
        # table is already clustered by (modality, source table, column).
        conn.execute(
            "CREATE INDEX overview_matrix_expanded_columns_rank_idx "
            "ON overview_matrix_expanded_columns "
            "(modality_key, source_table, sort_rank)"
        )

    _write_info(conn, min_groups, expanded_source_tables)
    conn.commit()


def _write_info(
    conn: sqlite3.Connection, min_groups: int, expanded_source_tables: list[str]
) -> None:
    conn.executemany(
        "INSERT INTO overview_matrix_info (key, value) VALUES (?, ?)",
        [
            ("schema_version", SCHEMA_VERSION),
            ("built_at", datetime.now(timezone.utc).isoformat()),
            ("min_groups_floor", str(min_groups)),
            ("materialize_top_m", str(MATERIALIZE_TOP_M)),
            ("expanded_source_tables", json.dumps(expanded_source_tables)),
        ],
    )
