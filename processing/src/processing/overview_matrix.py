"""Materialization of the collated cross-modality overview matrix (#222, #213).

`/api/collated-matrix` used to compute the whole perturbed-gene × modality
aggregation live on every request (~6.8 s), and the RNA-expression expansion
would have added another ~5.6 s on top. It is pure, deterministic SQL over the
dataset DB, so it is precomputed here — the same reasoning that moved the
combined p-values into their own build in #176 — and the API becomes a cheap
indexed read.

Every `overview_matrix`-flagged table is **expanded** into a set of heatmap
columns (#213 removed the old aggregated "status" columns entirely). The rows
are the experimentally perturbed genes. A table's columns come from one of three
axes, declared in config:

- **gene target** — one column per measured target gene (expression, perturb-seq,
  perturb-FISH). A target qualifies when it is FDR-significant across at least
  `min_groups` distinct perturbed-side groups, and only the top-M most-convergent
  are kept (the dense CRISPR screens have thousands).
- **long phenotype** (`overview_matrix_phenotype_column`) — one column per
  distinct value of a text column (behavioral parameter, cell subcluster). All
  distinct values are kept (these datasets have few).
- **wide phenotype** (`overview_matrix_phenotype_columns`) — one column per named
  numeric column (brain regions, behavior parameters), value aggregated per gene.

Each column carries a **metric** id naming its color scale (`neglog_p`,
`neglog_q`, `signed_neglog_p`, `activity_ratio`); each cell stores a single
`value` in that metric's units. The web color-scale registry turns (metric,
value) into a color and renders one legend bar per metric present.

Row ordering is deliberately *not* materialized: the API sorts genes with
JavaScript's ``localeCompare``, which Python cannot reproduce byte-for-byte.
"""

import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import click

from processing.build_info import read_build_uuid
from processing.combined_pvalues.collection import parse_link_tables_for_direction
from processing.my_logger import get_sspsygene_logger
from processing.sql_utils import sanitize_identifier
from processing.types.table_to_process_config import normalize_column_name


SCHEMA_VERSION = "3"

# -log10(p) clamp for neglog_* heatmap cells. The lower bound keeps every present
# cell visible against "no data"; the upper bound stops a single p ~ 1e-49 row
# (they exist) from owning the whole color ramp. This range is also the frontend
# neglog scale's domain, so clamping here doesn't lose anything.
NEG_LOG_P_MIN = 1.0
NEG_LOG_P_MAX = 20.0

# Metrics whose cell value is -log10(min significance) rather than a raw column
# value. For these the materializer transforms + clamps; the effect metrics
# (signed_neglog_p, activity_ratio) store the aggregated raw value verbatim.
_NEGLOG_METRICS = frozenset({"neglog_p", "neglog_q"})

# Response-side key prefix for a modality's sub-columns, e.g. `expr:<table>:SHANK3`.
# Stored in the DB so the web API doesn't hardcode it; unknown modalities fall
# back to their own key.
_COLUMN_PREFIXES = {
    "expression": "expr",
    "perturb_seq": "ps",
    "perturb_fish": "pf",
    "behavior": "beh",
}

# A gene-target column is kept only if it is FDR-significant across at least this
# many distinct perturbed-side groups. Fixed floor — the API/UI tunes *how many*
# columns per dataset to show, not this bar. Phenotype axes ignore it (few cols).
ELIGIBILITY_MIN_GROUPS = 2

# Only the top-M most-convergent columns per (modality, source table) are
# materialized. M is the largest "columns per dataset" the UI offers.
MATERIALIZE_TOP_M = 200

_TABLES = (
    "overview_matrix_genes",
    "overview_matrix_expansions",
    "overview_matrix_expanded_columns",
    "overview_matrix_expanded_cells",
    "overview_matrix_info",
)

# TEMP table holding the central genes allowed to be matrix rows. Every
# perturbed-gene read in this module goes through it, so there is exactly one
# place the row axis is decided. Populated by `_create_panel_filter` with the
# SSPsyGene consortium panel (minus controls), or — when no panel is supplied —
# with every non-control gene, which reproduces the pre-#228 behaviour.
_PANEL_TABLE = "matrix_panel_gene"


def load_panel_symbols(path: Path) -> list[str]:
    """Read the SSPsyGene gene list: one HGNC symbol per line, `#` comments."""
    symbols: list[str] = []
    with open(path, "r") as handle:
        for line in handle:
            symbol = line.strip()
            if symbol and not symbol.startswith("#"):
                symbols.append(symbol)
    if not symbols:
        raise ValueError(f"SSPsyGene gene list at {path} contains no symbols")
    return symbols


def resolve_panel_gene_ids(
    conn: sqlite3.Connection, symbols: list[str], src_schema: str = "main"
) -> set[int]:
    """Map panel symbols to `central_gene` ids, falling back to synonyms.

    The consortium sheet carries at least one retired symbol (`SUV420H1`, whose
    current HGNC symbol is `KMT5B`), and `central_gene.human_symbol` only holds
    the current one — so a plain equijoin silently drops consortium genes. Any
    symbol that resolves through neither path is logged, not swallowed.
    """
    log = get_sspsygene_logger()
    gene_ids: set[int] = set()
    unresolved: list[str] = []
    for symbol in symbols:
        row = conn.execute(
            f"SELECT id FROM {src_schema}.central_gene WHERE human_symbol = ?",
            (symbol,),
        ).fetchone()
        if row is None:
            row = conn.execute(
                f"""SELECT e.central_gene_id
                      FROM {src_schema}.extra_gene_synonyms e
                      JOIN {src_schema}.central_gene c ON c.id = e.central_gene_id
                     WHERE e.synonym = ? AND c.human_symbol IS NOT NULL
                     LIMIT 1""",
                (symbol,),
            ).fetchone()
        if row is None:
            unresolved.append(symbol)
        else:
            gene_ids.add(row[0])
    if unresolved:
        log.warning(
            "overview matrix: %d of %d SSPsyGene panel symbols did not resolve to "
            "a central gene and cannot appear as matrix rows: %s",
            len(unresolved),
            len(symbols),
            ", ".join(sorted(unresolved)),
        )
    return gene_ids


def _create_panel_filter(
    conn: sqlite3.Connection, panel_gene_ids: set[int] | None, src_schema: str
) -> None:
    conn.execute(f"DROP TABLE IF EXISTS temp.{_PANEL_TABLE}")
    conn.execute(f"CREATE TEMP TABLE {_PANEL_TABLE} (id INTEGER PRIMARY KEY)")
    if panel_gene_ids is None:
        conn.execute(
            f"""INSERT INTO {_PANEL_TABLE} (id)
                SELECT id FROM {src_schema}.central_gene WHERE kind != 'control'"""
        )
        return
    conn.executemany(
        f"INSERT OR IGNORE INTO {_PANEL_TABLE} (id) VALUES (?)",
        [(gene_id,) for gene_id in sorted(panel_gene_ids)],
    )
    # A control guide should never be on the panel, but the row axis must not
    # depend on that holding.
    conn.execute(
        f"""DELETE FROM {_PANEL_TABLE} WHERE id IN
            (SELECT id FROM {src_schema}.central_gene WHERE kind = 'control')"""
    )


def _create_schema(conn: sqlite3.Connection) -> None:
    for table in _TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(
        """CREATE TABLE overview_matrix_genes (
        central_gene_id INTEGER PRIMARY KEY,
        human_symbol TEXT)"""
    )
    conn.execute(
        """CREATE TABLE overview_matrix_expansions (
        modality_key TEXT PRIMARY KEY,
        column_prefix TEXT NOT NULL,
        source_tables TEXT NOT NULL,
        n_columns_total INTEGER NOT NULL)"""
    )
    # An expanded modality can fan out several source datasets (perturb-seq has
    # several; behavior has three with different metrics); `source_table` keeps
    # columns from different datasets distinct and lets the API group + label
    # them by dataset. `metric` names the color scale, `column_is_gene` drives
    # whether the column header links to a target-gene search.
    conn.execute(
        """CREATE TABLE overview_matrix_expanded_columns (
        modality_key TEXT NOT NULL,
        source_table TEXT NOT NULL,
        source_label TEXT,
        column_value TEXT NOT NULL,
        n_sig_groups INTEGER NOT NULL,
        min_p REAL NOT NULL,
        sort_rank INTEGER NOT NULL,
        metric TEXT NOT NULL,
        metric_domain TEXT,
        column_is_gene INTEGER NOT NULL,
        PRIMARY KEY (modality_key, source_table, column_value)) WITHOUT ROWID"""
    )
    # Clustered by column, not by gene: the read path selects a set of qualifying
    # columns and wants every gene's value for each, so a column-major key turns
    # the whole fetch into one contiguous range scan per column.
    conn.execute(
        """CREATE TABLE overview_matrix_expanded_cells (
        modality_key TEXT NOT NULL,
        source_table TEXT NOT NULL,
        column_value TEXT NOT NULL,
        central_gene_id INTEGER NOT NULL,
        value REAL NOT NULL,
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
    """Split a comma-separated column list, dropping unusable identifiers."""
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


def _group_to_genes(
    conn: sqlite3.Connection,
    base_table: str,
    link_table: str,
    group_expr: str,
    src_schema: str,
) -> dict[object, list[int]]:
    """Map each distinct perturbed-column value to its central gene ids.

    Rows sharing a perturbed-column value always resolve to the same gene set —
    the link rows are generated per value — so one representative row id per
    distinct value is enough, and the large link table is scanned once with a
    tiny `IN` filter. The invariant is asserted against the link table's row
    count; on any mismatch we fall back to the exact (slower) DISTINCT join.
    """
    log = get_sspsygene_logger()
    allowed = {row[0] for row in conn.execute(f"SELECT id FROM {_PANEL_TABLE}")}
    reps = conn.execute(
        f"SELECT {group_expr}, MIN(id), COUNT(*) "
        f"FROM {src_schema}.{base_table} GROUP BY {group_expr}"
    ).fetchall()
    rep_id_to_group = {rep_id: group for group, rep_id, _ in reps}
    rows_per_group = {group: n_rows for group, _, n_rows in reps}

    placeholders = ",".join("?" for _ in rep_id_to_group)
    full_mapping: dict[object, list[int]] = {group: [] for group in rows_per_group}
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
            group: [gene_id for gene_id in gene_ids if gene_id in allowed]
            for group, gene_ids in full_mapping.items()
        }

    log.warning(
        "overview matrix: %s link-row count %d != expected %d from the "
        "representative-row shortcut; falling back to the exact join",
        link_table,
        actual,
        expected,
    )
    mapping: dict[object, list[int]] = {group: [] for group in rows_per_group}
    for group, gene_id in conn.execute(
        f"""SELECT DISTINCT {group_expr}, lt.central_gene_id
              FROM {src_schema}.{base_table} t
              JOIN {src_schema}.{link_table} lt ON lt.id = t.id
             WHERE lt.central_gene_id IN (SELECT id FROM {_PANEL_TABLE})"""
    ):
        mapping.setdefault(group, []).append(gene_id)
    return mapping


def _resolve_source_columns(
    link_tables_raw: str | None, columns: set[str]
) -> dict[str, str | None]:
    """Read the target / perturbed source columns out of the link-table spec."""
    source_columns: dict[str, str | None] = {"target": None, "perturbed": None}
    for entry in (link_tables_raw or "").split(","):
        parts = entry.strip().split(":")
        if len(parts) < 3:
            continue
        candidate = normalize_column_name(parts[0])
        if parts[2] in source_columns and candidate in columns:
            source_columns[parts[2]] = candidate
    return source_columns


def _neg_log_p(p: float) -> float:
    """-log10(p), clamped to [1, 20]. p <= 0 (underflow) maps to the top."""
    if p <= 0:
        return NEG_LOG_P_MAX
    return round(min(max(-math.log10(p), NEG_LOG_P_MIN), NEG_LOG_P_MAX), 3)


def _materialize_pvalue_axis(
    conn: sqlite3.Connection,
    *,
    modality_key: str,
    table_name: str,
    source_label: str | None,
    base_table: str,
    link_table: str,
    group_expr: str,
    target_column: str,
    column_is_gene: bool,
    metric: str,
    metric_domain: str | None,
    p_col: str,
    fdr_col: str,
    min_groups: int,
    show_all: bool,
    src_schema: str,
) -> int:
    """Gene-target or long-phenotype axis: columns keyed by `target_column`.

    A cell is -log10(most significant p) per (perturbed gene, column value).
    Gene columns keep the ≥`min_groups` convergence floor + top-M cap; phenotype
    columns (`show_all`) keep every distinct value.
    """
    group_genes = _group_to_genes(conn, base_table, link_table, group_expr, src_schema)

    per_group = conn.execute(
        f"""SELECT {group_expr}, {target_column}, MIN({p_col}), MIN({fdr_col})
              FROM {src_schema}.{base_table}
             WHERE {target_column} IS NOT NULL AND {target_column} != ''
             GROUP BY 1, 2"""
    ).fetchall()

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

    if show_all:
        # Every column that has any data — phenotype datasets are small and the
        # user wants the raw columns, not just convergent ones.
        qualifying = {
            target: n_sig_by_target.get(target, 0) for target in min_p_by_target
        }
    else:
        qualifying = {
            target: n_sig
            for target, n_sig in n_sig_by_target.items()
            if n_sig >= min_groups and target in min_p_by_target
        }
    if not qualifying:
        return 0

    ordered = sorted(
        qualifying, key=lambda t: (-qualifying[t], min_p_by_target[t], str(t))
    )[:MATERIALIZE_TOP_M]
    kept = set(ordered)
    conn.executemany(
        "INSERT INTO overview_matrix_expanded_columns "
        "(modality_key, source_table, source_label, column_value, n_sig_groups, "
        " min_p, sort_rank, metric, metric_domain, column_is_gene) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                modality_key,
                table_name,
                source_label,
                str(target),
                qualifying[target],
                min_p_by_target[target],
                rank,
                metric,
                metric_domain,
                1 if column_is_gene else 0,
            )
            for rank, target in enumerate(ordered)
        ],
    )

    cells: dict[tuple[int, str], float] = {}
    for group, target, min_p, _min_fdr in per_group:
        if min_p is None or target not in kept:
            continue
        for gene_id in group_genes.get(group, ()):
            key = (gene_id, str(target))
            current = cells.get(key)
            if current is None or min_p < current:
                cells[key] = min_p
    conn.executemany(
        "INSERT INTO overview_matrix_expanded_cells "
        "(modality_key, source_table, column_value, central_gene_id, value) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (modality_key, table_name, target, gene_id, _neg_log_p(min_p))
            for (gene_id, target), min_p in cells.items()
        ],
    )
    click.echo(
        f"  Overview matrix: '{modality_key}' / {table_name} → "
        f"{len(ordered)} columns / {len(cells)} cells "
        f"(metric {metric}, {'all' if show_all else f'≥{min_groups} sig'})"
    )
    return len(ordered)


def _materialize_wide_axis(
    conn: sqlite3.Connection,
    *,
    modality_key: str,
    table_name: str,
    source_label: str | None,
    base_table: str,
    link_table: str,
    phenotype_columns: list[str],
    metric: str,
    metric_domain: str | None,
    src_schema: str,
) -> int:
    """Wide phenotype axis: each named numeric column is one column.

    The raw config name is the (short) column header; it is normalized to read
    the loaded DB column. The cell value aggregates that column across the gene's
    rows — max-magnitude for signed −log10(p), mean for effect ratios. Values are
    stored verbatim in the metric's units (the frontend scale clamps to domain).
    """
    log = get_sspsygene_logger()
    existing = _table_columns(conn, base_table, src_schema)
    signed = metric == "signed_neglog_p"

    per_column: dict[str, dict[int, float]] = {}
    labels: dict[str, str] = {}
    for raw_pc in phenotype_columns:
        pc = normalize_column_name(raw_pc)
        if pc not in existing:
            log.warning(
                "overview matrix: %s has no phenotype column %r (normalized %r), "
                "skipping it",
                table_name,
                raw_pc,
                pc,
            )
            continue
        rows = conn.execute(
            f"""SELECT lt.central_gene_id, t.{pc}
                  FROM {src_schema}.{base_table} t
                  JOIN {src_schema}.{link_table} lt ON t.id = lt.id
                 WHERE lt.central_gene_id IN (SELECT id FROM {_PANEL_TABLE})
                   AND t.{pc} IS NOT NULL"""
        ).fetchall()
        signed_agg: dict[int, float] = {}
        mean_acc: dict[int, list[float]] = {}
        for gene_id, raw in rows:
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            if signed:
                current = signed_agg.get(gene_id)
                if current is None or abs(v) > abs(current):
                    signed_agg[gene_id] = v
            else:
                mean_acc.setdefault(gene_id, []).append(v)
        agg = (
            signed_agg
            if signed
            else {g: sum(vals) / len(vals) for g, vals in mean_acc.items() if vals}
        )
        if not agg:
            continue
        per_column[pc] = agg
        labels[pc] = raw_pc

    if not per_column:
        return 0

    ordered = sorted(
        per_column, key=lambda pc: (-len(per_column[pc]), labels[pc])
    )[:MATERIALIZE_TOP_M]
    conn.executemany(
        "INSERT INTO overview_matrix_expanded_columns "
        "(modality_key, source_table, source_label, column_value, n_sig_groups, "
        " min_p, sort_rank, metric, metric_domain, column_is_gene) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                modality_key,
                table_name,
                source_label,
                labels[pc],
                len(per_column[pc]),
                0.0,
                rank,
                metric,
                metric_domain,
                0,
            )
            for rank, pc in enumerate(ordered)
        ],
    )
    conn.executemany(
        "INSERT INTO overview_matrix_expanded_cells "
        "(modality_key, source_table, column_value, central_gene_id, value) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (modality_key, table_name, labels[pc], gene_id, round(value, 3))
            for pc in ordered
            for gene_id, value in per_column[pc].items()
        ],
    )
    n_cells = sum(len(per_column[pc]) for pc in ordered)
    click.echo(
        f"  Overview matrix: '{modality_key}' / {table_name} → "
        f"{len(ordered)} columns / {n_cells} cells (metric {metric}, wide)"
    )
    return len(ordered)


def _materialize_expansion(
    conn: sqlite3.Connection,
    *,
    modality_key: str,
    table_name: str,
    source_label: str | None,
    pvalue_column: str | None,
    fdr_column: str | None,
    link_tables_raw: str | None,
    phenotype_column: str | None,
    phenotype_columns: list[str],
    metric: str | None,
    metric_domain: str | None,
    min_groups: int,
    src_schema: str,
) -> int:
    """Materialize one expanded (modality, source table). Returns column count.

    Dispatches on the declared column axis: gene target, long phenotype column,
    or wide phenotype columns.
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

    if phenotype_columns:
        # WIDE — metric is required by config validation for this axis.
        return _materialize_wide_axis(
            conn,
            modality_key=modality_key,
            table_name=table_name,
            source_label=source_label,
            base_table=base_table,
            link_table=link_table,
            phenotype_columns=phenotype_columns,
            metric=metric or "signed_neglog_p",
            metric_domain=metric_domain,
            src_schema=src_schema,
        )

    columns = _table_columns(conn, base_table, src_schema)
    source_columns = _resolve_source_columns(link_tables_raw, columns)
    group_expr = source_columns["perturbed"] or "''"

    if phenotype_column:
        target_column = phenotype_column
        column_is_gene = False
        show_all = True
    else:
        target_column = source_columns["target"]
        column_is_gene = True
        show_all = False
    if not target_column or target_column not in columns:
        log.warning(
            "overview matrix: %s has no usable column axis, skipping expansion",
            table_name,
        )
        return 0

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
    # Default metric: a table with only an FDR/qval colours on the FDR scale.
    resolved_metric = metric or ("neglog_q" if not pvalue_cols and fdr_cols else "neglog_p")

    return _materialize_pvalue_axis(
        conn,
        modality_key=modality_key,
        table_name=table_name,
        source_label=source_label,
        base_table=base_table,
        link_table=link_table,
        group_expr=group_expr,
        target_column=target_column,
        column_is_gene=column_is_gene,
        metric=resolved_metric,
        metric_domain=metric_domain,
        p_col=p_col,
        fdr_col=fdr_col,
        min_groups=min_groups,
        show_all=show_all,
        src_schema=src_schema,
    )


def materialize_overview_matrix(
    conn: sqlite3.Connection,
    *,
    no_index: bool = False,
    min_groups: int = ELIGIBILITY_MIN_GROUPS,
    src_schema: str = "main",
    panel_gene_ids: set[int] | None = None,
) -> None:
    """Precompute the overview matrix (#222, #213).

    Writes the `overview_matrix_*` tables into `conn`'s main schema, reading the
    dataset tables from `src_schema`. `run_overview_matrix` passes
    ``src_schema="src"`` with the dataset DB ATTACHed read-only; the in-process
    path (tests) leaves it ``"main"``.

    `min_groups` is the gene-target eligibility floor (a target gene is a column
    only when FDR-significant across at least this many perturbed groups); at
    most `MATERIALIZE_TOP_M` most-convergent are kept per (modality, source
    table). Phenotype axes ignore the floor and keep every distinct column.

    `panel_gene_ids` restricts the row axis to the SSPsyGene consortium panel
    (#228). It also gates which perturbed groups count toward a column's
    convergence, so columns are scored over the genes actually displayed. Pass
    ``None`` to keep every non-control perturbed gene, the pre-#228 behaviour.
    """
    min_groups = max(1, min_groups)
    _create_schema(conn)
    _create_panel_filter(conn, panel_gene_ids, src_schema)

    modality_keys, assay_to_modalities = _load_modalities(conn, src_schema)
    if not modality_keys:
        _write_info(conn, min_groups, [], panel_gene_ids, src_schema)
        conn.commit()
        return

    # Prod-labelled inputs only (#225), whichever main DB we are reading. The
    # overview tables record contributing table names (expansions.source_tables,
    # expanded_columns/_cells.source_table, info.expanded_source_tables), so a
    # run against dev's superset would carry int-only names into every copy.
    # Restricting to prod makes the file destination-independent, which is what
    # lets it be built once on dev and copied verbatim to prod and int.
    # Guarded on the table existing so pre-#225 DBs and the in-memory test
    # fixtures still materialize every flagged table.
    prod_clause = ""
    if conn.execute(
        f"SELECT 1 FROM {src_schema}.sqlite_master "
        f"WHERE type='table' AND name='dataset_destinations'"
    ).fetchone():
        prod_clause = (
            f" AND table_name IN (SELECT table_name FROM "
            f"{src_schema}.dataset_destinations WHERE destination = 'prod')"
        )
    source_rows = conn.execute(
        f"""SELECT table_name, assay, pvalue_column, fdr_column, link_tables,
                   short_label,
                   overview_matrix_phenotype_column,
                   overview_matrix_phenotype_columns,
                   overview_matrix_metric, overview_matrix_metric_domain
             FROM {src_schema}.data_tables
            WHERE include_in_overview_matrix = 1
              AND expand_in_overview_matrix = 1{prod_clause}"""
    ).fetchall()

    expanded_source_tables: list[str] = []
    perturbed_link_tables: list[str] = []
    for (
        table_name,
        assay,
        pvalue_column,
        fdr_column,
        link_tables_raw,
        short_label,
        phenotype_column,
        phenotype_columns_raw,
        metric,
        metric_domain,
    ) in source_rows:
        modality_keys_for_table = _modality_keys_for(assay, assay_to_modalities)
        if not modality_keys_for_table:
            continue
        modality_key = modality_keys_for_table[0]

        # Genes present in this table (its rows), regardless of column success —
        # the perturbed-gene axis of the whole matrix is their union.
        for link_table in parse_link_tables_for_direction(link_tables_raw or "", "perturbed"):
            perturbed_link_tables.append(link_table)

        try:
            phenotype_columns = (
                json.loads(phenotype_columns_raw) if phenotype_columns_raw else []
            )
        except (TypeError, ValueError):
            phenotype_columns = []

        n_columns = _materialize_expansion(
            conn,
            modality_key=modality_key,
            table_name=table_name,
            source_label=short_label,
            pvalue_column=pvalue_column,
            fdr_column=fdr_column,
            link_tables_raw=link_tables_raw,
            phenotype_column=phenotype_column,
            phenotype_columns=phenotype_columns,
            metric=metric,
            metric_domain=metric_domain,
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

    # Rows: every perturbed (non-control) gene across the expanded tables.
    for link_table in dict.fromkeys(perturbed_link_tables):
        try:
            safe_link = sanitize_identifier(link_table)
        except ValueError:
            continue
        conn.execute(
            f"""INSERT OR IGNORE INTO overview_matrix_genes (central_gene_id, human_symbol)
               SELECT DISTINCT lt.central_gene_id, cg.human_symbol
                 FROM {src_schema}.{safe_link} lt
                 JOIN {src_schema}.central_gene cg ON cg.id = lt.central_gene_id
                WHERE lt.central_gene_id IN (SELECT id FROM {_PANEL_TABLE})"""
        )

    if not no_index:
        conn.execute(
            "CREATE INDEX overview_matrix_expanded_columns_rank_idx "
            "ON overview_matrix_expanded_columns "
            "(modality_key, source_table, sort_rank)"
        )

    _write_info(
        conn, min_groups, expanded_source_tables, panel_gene_ids, src_schema
    )
    conn.commit()


def _write_info(
    conn: sqlite3.Connection,
    min_groups: int,
    expanded_source_tables: list[str],
    panel_gene_ids: set[int] | None = None,
    src_schema: str = "main",
) -> None:
    rows = [
        ("schema_version", SCHEMA_VERSION),
        ("built_at", datetime.now(timezone.utc).isoformat()),
        ("min_groups_floor", str(min_groups)),
        ("materialize_top_m", str(MATERIALIZE_TOP_M)),
        ("expanded_source_tables", json.dumps(expanded_source_tables)),
        # Whether the row axis was restricted to the consortium panel (#228),
        # so a reader can tell an unfiltered build from a filtered one.
        ("sspsygene_panel_filtered", "1" if panel_gene_ids is not None else "0"),
        (
            "sspsygene_panel_gene_count",
            str(len(panel_gene_ids)) if panel_gene_ids is not None else "",
        ),
    ]
    # Identity of the main DB this matrix was computed from (#225), so the web
    # app can tell a stale overview DB from a current one — and so a *copied*
    # overview DB still matches, which a file (mtime, size) fingerprint could
    # not. Absent for source DBs predating #225.
    source_uuid = read_build_uuid(conn, src_schema)
    if source_uuid is not None:
        rows.append(("source_build_uuid", source_uuid))
    conn.executemany(
        "INSERT INTO overview_matrix_info (key, value) VALUES (?, ?)", rows
    )
