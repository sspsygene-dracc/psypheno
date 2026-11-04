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

Alongside the expansion, each table is also collapsed to a **single summary
column** (#234): per perturbed gene, how many of that table's readouts came back
significant, plus the strongest one. That count is deliberately taken over
*every* readout — not over the materialized columns, which are already filtered
to the top-M that converge across ≥`min_groups` perturbations, and so exclude
exactly the gene-specific responses a breadth count should include.

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
from processing.overview_phenotypes import (
    TESTS_TABLE,
    PhenotypeSource,
    create_phenotype_schema,
    materialize_phenotype_collated,
)
from processing.overview_collated import (
    COLLATE_GROUPS,
    COLLATED_TABLES,
    CollateSource,
    create_collated_schema,
    materialize_collated,
    target_link_for,
)
from processing.sql_utils import sanitize_identifier
from processing.types.table_to_process_config import normalize_column_name


SCHEMA_VERSION = "8"

# -log10(p) clamp for neglog_* heatmap cells. The lower bound keeps every present
# cell visible against "no data"; the upper bound stops a single p ~ 1e-49 row
# (they exist) from owning the whole color ramp. This is the *storage* range: each
# frontend scale in web/lib/matrix-color-scales.ts carries its own display domain,
# which may be narrower (neglog_q is [1, 2]) and re-clamps at render time.
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

# Significance bar for the per-readout counts. The p-value axis has a real FDR
# to test; the wide axis only carries a signed -log10(nominal p), so it tests
# |value| against -log10(0.05). The two are NOT the same quantity, which is why
# each summary column records which rule produced its count (`sig_rule`) and the
# frontend words the popover from it rather than saying "significant" flatly.
SIG_ALPHA = 0.05
SIG_RULE_FDR = "fdr<0.05"
SIG_RULE_NOMINAL_P = "nominal_p<0.05"
_SIGNED_NEGLOG_P_SIG = -math.log10(SIG_ALPHA)  # 1.301
_SHARED_MIN_VALUES = 3
_SHARED_MIN_FRACTION = 0.25

_TABLES = (
    "overview_matrix_genes",
    "overview_matrix_expansions",
    "overview_matrix_expanded_columns",
    "overview_matrix_expanded_cells",
    "overview_matrix_summary_columns",
    "overview_matrix_summary_cells",
    "overview_matrix_inferred_cells",
    "overview_matrix_shared_cells",
    *COLLATED_TABLES,
    TESTS_TABLE,
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
    # The per-dataset summary column (#234). Self-sufficient on purpose: it
    # carries `modality_key` + `column_prefix` rather than joining
    # `overview_matrix_expansions`, because a dataset whose readouts all fail the
    # convergence floor contributes no expanded columns and so never gets an
    # expansions row — but it still has a perfectly good breadth summary.
    conn.execute(
        """CREATE TABLE overview_matrix_summary_columns (
        source_table TEXT PRIMARY KEY,
        modality_key TEXT NOT NULL,
        column_prefix TEXT NOT NULL,
        source_label TEXT,
        base_metric TEXT NOT NULL,
        sig_rule TEXT NOT NULL,
        n_readouts_total INTEGER NOT NULL) WITHOUT ROWID"""
    )
    # `n_sig` is stored raw, not pre-scaled: the API applies log10(1 + n_sig) at
    # read time, so the color scale can be retuned without a rebuild.
    conn.execute(
        """CREATE TABLE overview_matrix_summary_cells (
        source_table TEXT NOT NULL,
        central_gene_id INTEGER NOT NULL,
        n_sig INTEGER NOT NULL,
        n_measured INTEGER NOT NULL,
        best_value REAL NOT NULL,
        n_inferred INTEGER NOT NULL DEFAULT 0,
        inferred_basis TEXT,
        PRIMARY KEY (source_table, central_gene_id)) WITHOUT ROWID"""
    )
    # "Tested, not significant" cells *inferred* for significant-only tables
    # (see `infer_measured_readouts`). Kept apart from the expanded cells: they
    # carry no value — the source never published one — and every existing
    # reader of expanded_cells keeps meaning "reported". `basis` is "screen"
    # (the perturbation has reported rows in that context) or "library" (it is
    # only on the paper's perturbation list — a weaker assumption).
    conn.execute(
        """CREATE TABLE overview_matrix_inferred_cells (
        modality_key TEXT NOT NULL,
        source_table TEXT NOT NULL,
        column_value TEXT NOT NULL,
        central_gene_id INTEGER NOT NULL,
        basis TEXT NOT NULL,
        PRIMARY KEY (modality_key, source_table, column_value, central_gene_id))
        WITHOUT ROWID"""
    )
    # Phenotype cells whose values also appear in another table for the same gene:
    # the same measurement published twice (see `materialize_shared_cells`).
    conn.execute(
        """CREATE TABLE overview_matrix_shared_cells (
        modality_key TEXT NOT NULL,
        source_table TEXT NOT NULL,
        column_value TEXT NOT NULL,
        central_gene_id INTEGER NOT NULL,
        shared_with_table TEXT NOT NULL,
        shared_with_label TEXT NOT NULL,
        PRIMARY KEY (modality_key, source_table, column_value, central_gene_id,
                     shared_with_table))
        WITHOUT ROWID"""
    )
    create_collated_schema(conn)
    create_phenotype_schema(conn)
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


def _phenotype_source(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    study: str,
    study_label: str,
    terms_raw: str,
    link_tables_raw: str | None,
    phenotype_column: str | None,
    pvalue_column: str | None,
    fdr_column: str | None,
    effect_column: str | None,
    src_schema: str,
) -> PhenotypeSource | None:
    """Describe a phenotype table for the by-readout view; warn on unmapped columns."""
    log = get_sspsygene_logger()
    base_table = sanitize_identifier(table_name)
    links = parse_link_tables_for_direction(link_tables_raw or "", "perturbed")
    if not links:
        return None
    terms: dict[str, str] = json.loads(terms_raw)
    columns = _table_columns(conn, base_table, src_schema)
    if phenotype_column:
        if not pvalue_column:
            return None
        declared = set(terms)
        present = {
            str(row[0])
            for row in conn.execute(
                f"SELECT DISTINCT {phenotype_column} "
                f"FROM {src_schema}.{base_table} "
                f"WHERE {phenotype_column} IS NOT NULL"
            )
        }
        by_column = terms
        column_labels: dict[str, str] = {}
    else:
        by_column = {normalize_column_name(k): v for k, v in terms.items()}
        column_labels = {normalize_column_name(k): k for k in terms}
        declared = set(by_column)
        present = declared & columns
    if present - declared:
        log.warning(
            "overview matrix: %s has phenotype columns with no term: %s",
            table_name,
            sorted(present - declared),
        )
    return PhenotypeSource(
        table_name=table_name,
        study=study,
        study_label=study_label,
        base_table=base_table,
        perturbed_link=links[0],
        term_by_column=by_column,
        phenotype_column=phenotype_column,
        p_col=pvalue_column,
        fdr_col=fdr_column,
        effect_col=(_split_columns(effect_column) or [None])[0],
        columns=columns,
        column_labels=column_labels,
    )


def _study_label(
    medium_label: str | None, short_label: str | None, table_name: str
) -> str:
    """Short study name: the "Author Year" head of the table's medium label."""
    return (medium_label or "").split(" - ")[0].strip() or short_label or table_name


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


def _write_summary(
    conn: sqlite3.Connection,
    *,
    modality_key: str,
    table_name: str,
    source_label: str | None,
    base_metric: str,
    sig_rule: str,
    n_readouts_total: int,
    n_sig: dict[int, int],
    n_measured: dict[int, int],
    best: dict[int, float],
    n_inferred: dict[int, int] | None = None,
    library_only: set[int] | None = None,
) -> None:
    """Write one dataset’s collapsed summary column and its cells (#234).

    A cell is (n_sig, n_measured, best_value) for one perturbed gene over *all*
    of the table’s readouts. Genes with no measurement at all are simply absent
    — the matrix is sparse, and the frontend draws a missing cell differently
    from a measured-but-empty one (n_sig = 0).

    `n_inferred` (significant-only tables) counts how many of `n_measured` were
    inferred rather than reported. A gene whose readouts are *all* inferred has
    no reported value, so its `best_value` is 0 — below every metric's range.
    """
    n_inferred = n_inferred or {}
    library_only = library_only or set()
    if not n_measured:
        return
    conn.execute(
        "INSERT INTO overview_matrix_summary_columns "
        "(source_table, modality_key, column_prefix, source_label, base_metric, "
        " sig_rule, n_readouts_total) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            table_name,
            modality_key,
            _COLUMN_PREFIXES.get(modality_key, modality_key),
            source_label,
            base_metric,
            sig_rule,
            n_readouts_total,
        ),
    )
    conn.executemany(
        "INSERT INTO overview_matrix_summary_cells "
        "(source_table, central_gene_id, n_sig, n_measured, best_value, "
        " n_inferred, inferred_basis) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                table_name,
                gene_id,
                n_sig.get(gene_id, 0),
                measured,
                round(best[gene_id], 3) if gene_id in best else 0.0,
                n_inferred.get(gene_id, 0),
                (
                    ("library" if gene_id in library_only else "screen")
                    if n_inferred.get(gene_id)
                    else None
                ),
            )
            for gene_id, measured in sorted(n_measured.items())
            if gene_id in best or n_inferred.get(gene_id)
        ],
    )
    click.echo(
        f"  Overview matrix: \'{modality_key}\' / {table_name} summary → "
        f"{len(n_measured)} genes over {n_readouts_total} readouts ({sig_rule})"
    )


def infer_measured_readouts(
    rows: list[tuple[object, object, str]],
    group_genes: dict[object, list[int]],
    library_gene_ids: set[int],
) -> dict[int, set[str]]:
    """Readouts each perturbed gene was measured on, for a significant-only table.

    `rows` are the table's distinct (perturbed group, context, readout) triples
    — every one a reported hit. In a pooled screen all perturbations are read
    out on the same transcriptomes, so:

    * a readout reported for *any* perturbation in context C was measured in C;
    * a perturbation was tested in C if it has a reported row in C. (Tested in
      C without a single hit there is indistinguishable from untested — e.g.
      too few cells — so this stays a lower bound.)
    * a `library_gene_ids` gene (from the paper's perturbation list) with no
      reported row at all is assumed tested in every context *that appears in
      the table* — the populations the authors could test at all. This is a
      weaker basis (its per-context cell counts are unknown), which is why the
      caller records it separately as basis "library".

    Returns gene id → readouts measured (reported ∪ inferred). Reported pairs
    are always included, since a reported row puts its readout in its context.
    """
    measured_in_context: dict[object, set[str]] = defaultdict(set)
    gene_contexts: dict[int, set[object]] = defaultdict(set)
    for group, context, readout in rows:
        measured_in_context[context].add(readout)
        for gene_id in group_genes.get(group, ()):
            gene_contexts[gene_id].add(context)
    all_contexts = set(measured_in_context)
    for gene_id in library_gene_ids:
        if gene_id not in gene_contexts:
            gene_contexts[gene_id] = set(all_contexts)
    measured: dict[int, set[str]] = {}
    for gene_id, contexts in gene_contexts.items():
        readouts: set[str] = set()
        for context in contexts:
            readouts |= measured_in_context[context]
        measured[gene_id] = readouts
    return measured


def _resolve_perturbation_values(
    conn: sqlite3.Connection,
    values: list[str],
    species: str | None,
    src_schema: str,
) -> tuple[set[int], list[str]]:
    """Map perturbation-library symbols to panel central gene ids.

    For library entries with no reported row — they have no link-table rows to
    resolve through. Mouse symbols match `central_gene.mouse_symbols` (a
    comma-joined list); anything else matches `human_symbol`, then synonyms.
    Returns (panel gene ids, values that resolved to no gene at all).
    """
    gene_ids: set[int] = set()
    unresolved: list[str] = []
    mouse = "mouse" in (species or "")
    has_synonyms = conn.execute(
        f"SELECT 1 FROM {src_schema}.sqlite_master "
        f"WHERE type = 'table' AND name = 'extra_gene_synonyms'"
    ).fetchone() is not None
    for value in values:
        if mouse:
            # LIKE narrows the scan; it is case-insensitive in SQLite, so the
            # exact list-member check happens in Python.
            rows = [
                (gene_id,)
                for gene_id, symbols in conn.execute(
                    f"""SELECT id, mouse_symbols FROM {src_schema}.central_gene
                         WHERE mouse_symbols LIKE '%' || ? || '%'""",
                    (value,),
                )
                if value in (symbols or "").split(",")
            ]
        else:
            rows = conn.execute(
                f"SELECT id FROM {src_schema}.central_gene WHERE human_symbol = ?",
                (value,),
            ).fetchall()
            if not rows and has_synonyms:
                rows = conn.execute(
                    f"""SELECT central_gene_id FROM {src_schema}.extra_gene_synonyms
                         WHERE synonym = ? LIMIT 1""",
                    (value,),
                ).fetchall()
        if not rows:
            unresolved.append(value)
            continue
        gene_ids.update(gene_id for (gene_id,) in rows)
    allowed = {row[0] for row in conn.execute(f"SELECT id FROM {_PANEL_TABLE}")}
    return gene_ids & allowed, unresolved


def _infer_for_table(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    base_table: str,
    group_expr: str,
    target_column: str,
    group_genes: dict[object, list[int]],
    significant_only: dict[str, list[str]] | None,
    species: str | None,
    src_schema: str,
) -> tuple[dict[int, set[str]], set[int]] | None:
    """(measured readouts per gene, library-only genes) for a significant-only
    table, else None.

    Library perturbations with no reported row become matrix rows here: they
    were tested, and "no significant readout" is exactly what the matrix should
    show for them.
    """
    if significant_only is None:
        return None
    log = get_sspsygene_logger()
    columns = _table_columns(conn, base_table, src_schema)
    context_columns = list(significant_only.get("context_columns") or [])
    context_expr = _context_expr(context_columns, columns)
    if context_expr is None:
        log.warning(
            "overview matrix: %s declares significant_only context columns %s "
            "that aren't all in the table; skipping inference",
            table_name,
            context_columns,
        )
        return None
    rows = [
        (group, context, str(target))
        for group, context, target in conn.execute(
            f"""SELECT DISTINCT {group_expr}, {context_expr}, {target_column}
                  FROM {src_schema}.{base_table}
                 WHERE {target_column} IS NOT NULL AND {target_column} != ''"""
        )
    ]
    library_values = list(significant_only.get("tested_perturbations") or [])
    library_gene_ids, unresolved = _resolve_perturbation_values(
        conn, library_values, species, src_schema
    )
    if unresolved:
        log.warning(
            "overview matrix: %s significant_only.tested_perturbations — %d value(s) "
            "resolve to no gene: %s",
            table_name,
            len(unresolved),
            ", ".join(unresolved),
        )
    reported_gene_ids = {g for genes in group_genes.values() for g in genes}
    library_only = library_gene_ids - reported_gene_ids
    if library_only:
        conn.executemany(
            f"""INSERT OR IGNORE INTO overview_matrix_genes (central_gene_id, human_symbol)
                SELECT id, human_symbol FROM {src_schema}.central_gene WHERE id = ?""",
            [(gene_id,) for gene_id in sorted(library_only)],
        )
    measured = infer_measured_readouts(rows, group_genes, library_gene_ids)
    click.echo(
        f"  Overview matrix: {table_name} is significant-only → tested universe "
        f"inferred over {len({c for _, c, _ in rows})} context(s); "
        f"{len(library_only)} library-only perturbed gene(s) added as rows"
    )
    return measured, library_only


def _context_expr(context_columns: list[str], columns: set[str]) -> str | None:
    """SQL for a row's screen context: '' (one context) or the joined columns.

    None when a declared context column isn't in the table — the caller skips
    inference rather than silently treating the table as one context.
    """
    if not context_columns:
        return "''"
    if any(col not in columns for col in context_columns):
        return None
    return " || char(31) || ".join(f"COALESCE({col}, '')" for col in context_columns)


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
    significant_only: dict[str, list[str]] | None = None,
    species: str | None = None,
) -> int:
    """Gene-target or long-phenotype axis: columns keyed by `target_column`.

    A cell is -log10(most significant p) per (perturbed gene, column value).
    Gene columns keep the ≥`min_groups` convergence floor + top-M cap; phenotype
    columns (`show_all`) keep every distinct value.

    `significant_only` (gene axis only): the source published only its hits, so
    unreported pairs are split into "tested, not significant (inferred)" —
    written to `overview_matrix_inferred_cells` and counted in the summary —
    and "not measured" (absent). See `infer_measured_readouts`.
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

    # Per-dataset summary column (#234). Counted over EVERY target, before the
    # convergence floor and the top-M cut, so a readout that responds to only one
    # perturbation still counts — which is the whole point of a breadth summary.
    # Walked target-major because one gene can sit in several perturbed groups
    # (SHANK3’s two genotypes), and a target must count once per gene, not once
    # per group. The panel restriction rides on `group_genes`; `per_group` itself
    # is unfiltered, so counting straight off it would admit controls and
    # off-panel perturbations.
    by_target: dict[str, list[tuple[object, float, float | None]]] = defaultdict(list)
    for group, target, min_p, min_fdr in per_group:
        if min_p is None or not group_genes.get(group):
            continue
        by_target[str(target)].append((group, min_p, min_fdr))

    sum_n_sig: dict[int, int] = defaultdict(int)
    sum_n_measured: dict[int, int] = defaultdict(int)
    sum_best_p: dict[int, float] = {}
    for entries in by_target.values():
        measured_genes: set[int] = set()
        sig_genes: set[int] = set()
        for group, min_p, min_fdr in entries:
            genes = group_genes.get(group, ())
            measured_genes.update(genes)
            # A NULL FDR counts as not significant, matching the column
            # eligibility rule below. A table carrying only a qval has
            # `p_col is fdr_col`, so this tests that qval.
            if min_fdr is not None and min_fdr < SIG_ALPHA:
                sig_genes.update(genes)
            for gene_id in genes:
                current = sum_best_p.get(gene_id)
                if current is None or min_p < current:
                    sum_best_p[gene_id] = min_p
        for gene_id in measured_genes:
            sum_n_measured[gene_id] += 1
        for gene_id in sig_genes:
            sum_n_sig[gene_id] += 1

    inference = _infer_for_table(
        conn,
        table_name=table_name,
        base_table=base_table,
        group_expr=group_expr,
        target_column=target_column,
        group_genes=group_genes,
        significant_only=significant_only if column_is_gene else None,
        species=species,
        src_schema=src_schema,
    )
    measured, library_only = inference if inference is not None else (None, set())
    sum_n_inferred: dict[int, int] = {}
    if measured is not None:
        reported_by_gene: dict[int, set[str]] = defaultdict(set)
        for target, entries in by_target.items():
            for group, _min_p, _min_fdr in entries:
                for gene_id in group_genes.get(group, ()):
                    reported_by_gene[gene_id].add(target)
        for gene_id, readouts in measured.items():
            n_inferred = len(readouts - reported_by_gene.get(gene_id, set()))
            sum_n_measured[gene_id] = len(readouts | reported_by_gene.get(gene_id, set()))
            if n_inferred:
                sum_n_inferred[gene_id] = n_inferred

    _write_summary(
        conn,
        modality_key=modality_key,
        table_name=table_name,
        source_label=source_label,
        base_metric=metric,
        sig_rule=SIG_RULE_FDR,
        n_readouts_total=len(by_target),
        n_sig=sum_n_sig,
        n_measured=sum_n_measured,
        best={g: _neg_log_p(p) for g, p in sum_best_p.items()},
        n_inferred=sum_n_inferred,
        library_only=library_only,
    )

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
    kept_str = {str(t) for t in ordered}
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
    inferred_cells: list[tuple[str, str, str, int, str]] = []
    if measured is not None:
        for gene_id, readouts in measured.items():
            basis = "library" if gene_id in library_only else "screen"
            for target in readouts & kept_str:
                if (gene_id, target) not in cells:
                    inferred_cells.append(
                        (modality_key, table_name, target, gene_id, basis)
                    )
        conn.executemany(
            "INSERT INTO overview_matrix_inferred_cells "
            "(modality_key, source_table, column_value, central_gene_id, basis) "
            "VALUES (?, ?, ?, ?, ?)",
            inferred_cells,
        )
    click.echo(
        f"  Overview matrix: '{modality_key}' / {table_name} → "
        f"{len(ordered)} columns / {len(cells)} cells"
        + (f" + {len(inferred_cells)} inferred n.s." if measured is not None else "")
        + f" (metric {metric}, {'all' if show_all else f'≥{min_groups} sig'})"
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

    return _write_phenotype_axis(
        conn,
        modality_key=modality_key,
        table_name=table_name,
        source_label=source_label,
        per_column=per_column,
        labels=labels,
        metric=metric,
        metric_domain=metric_domain,
    )


def _materialize_long_signed_axis(
    conn: sqlite3.Connection,
    *,
    modality_key: str,
    table_name: str,
    source_label: str | None,
    base_table: str,
    link_table: str,
    phenotype_column: str,
    pvalue_column: str,
    effect_column: str,
    metric_domain: str | None,
    src_schema: str,
) -> int:
    """Long phenotype axis with a direction: signed −log10(p) per column value.

    The p-value gives the magnitude and the effect column the sign, so a long
    table lands on the same scale as a wide `signed_neglog_p` table.
    """
    rows = conn.execute(
        f"""SELECT lt.central_gene_id, t.{phenotype_column}, t.{pvalue_column},
                   t.{effect_column}
              FROM {src_schema}.{base_table} t
              JOIN {src_schema}.{link_table} lt ON t.id = lt.id
             WHERE lt.central_gene_id IN (SELECT id FROM {_PANEL_TABLE})
               AND t.{phenotype_column} IS NOT NULL
               AND t.{pvalue_column} IS NOT NULL
               AND t.{effect_column} IS NOT NULL"""
    ).fetchall()
    per_column: dict[str, dict[int, float]] = {}
    for gene_id, column_value, raw_p, raw_effect in rows:
        try:
            p, effect = float(raw_p), float(raw_effect)
        except (TypeError, ValueError):
            continue
        value = math.copysign(-math.log10(max(p, 1e-300)), effect)
        agg = per_column.setdefault(str(column_value), {})
        current = agg.get(gene_id)
        if current is None or abs(value) > abs(current):
            agg[gene_id] = value
    return _write_phenotype_axis(
        conn,
        modality_key=modality_key,
        table_name=table_name,
        source_label=source_label,
        per_column=per_column,
        labels={column: column for column in per_column},
        metric="signed_neglog_p",
        metric_domain=metric_domain,
    )


def _write_phenotype_axis(
    conn: sqlite3.Connection,
    *,
    modality_key: str,
    table_name: str,
    source_label: str | None,
    per_column: dict[str, dict[int, float]],
    labels: dict[str, str],
    metric: str,
    metric_domain: str | None,
) -> int:
    """Write a phenotype axis's summary, columns and cells. Returns column count."""
    log = get_sspsygene_logger()
    signed = metric == "signed_neglog_p"

    # Per-dataset summary column (#234). `per_column` is already panel-filtered
    # by SQL and holds every phenotype column that had data, before the top-M cut.
    if signed:
        sum_n_sig: dict[int, int] = defaultdict(int)
        sum_n_measured: dict[int, int] = defaultdict(int)
        sum_best: dict[int, float] = {}
        for agg in per_column.values():
            for gene_id, value in agg.items():
                sum_n_measured[gene_id] += 1
                # A nominal p, not an FDR — hence the distinct `sig_rule`, so the
                # popover doesn’t claim FDR control this axis never had.
                if abs(value) >= _SIGNED_NEGLOG_P_SIG:
                    sum_n_sig[gene_id] += 1
                current = sum_best.get(gene_id)
                if current is None or abs(value) > abs(current):
                    sum_best[gene_id] = value
        _write_summary(
            conn,
            modality_key=modality_key,
            table_name=table_name,
            source_label=source_label,
            base_metric=metric,
            sig_rule=SIG_RULE_NOMINAL_P,
            n_readouts_total=len(per_column),
            n_sig=sum_n_sig,
            n_measured=sum_n_measured,
            best=sum_best,
        )
    else:
        # An effect ratio has no significance notion at all (a value at the pivot
        # means "measured, unchanged" — real evidence, not an absence of it), so
        # there is nothing to count and the dataset gets no summary column.
        log.warning(
            "overview matrix: %s uses metric %r, which has no significance "
            "notion — no summary column will be written for it",
            table_name,
            metric,
        )

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
        f"{len(ordered)} columns / {n_cells} cells (metric {metric}, phenotype)"
    )
    return len(ordered)


def materialize_shared_cells(
    conn: sqlite3.Connection,
    labels: dict[str, str],
    evidence_sources: dict[str, str],
) -> None:
    """Record phenotype cells that repeat another table's values for a gene.

    Column names differ between papers, so values are compared per gene rather
    than per column: stored at 3 decimals, a value also present in the other table
    for that gene is a match. Small values collide by chance, so a gene only
    counts once at least `_SHARED_MIN_VALUES`, and at least `_SHARED_MIN_FRACTION`
    of the smaller table's values for it, match.

    `evidence_sources` (table -> declared source) is what pooling acts on; this
    only marks cells, and warns when reuse hasn't been declared.
    """
    log = get_sspsygene_logger()
    matches: dict[tuple[str, str, str, int], set[str]] = defaultdict(set)
    for modality, table, other, gene_id, column_value in conn.execute(
        """SELECT a.modality_key, a.source_table, b.source_table,
                  a.central_gene_id, a.column_value
             FROM overview_matrix_expanded_cells a
             JOIN overview_matrix_expanded_cells b
               ON b.modality_key = a.modality_key
              AND b.central_gene_id = a.central_gene_id
              AND b.source_table <> a.source_table
              AND ABS(b.value) = ABS(a.value)
             JOIN overview_matrix_expanded_columns ca
               ON ca.modality_key = a.modality_key
              AND ca.source_table = a.source_table
              AND ca.column_value = a.column_value
             JOIN overview_matrix_expanded_columns cb
               ON cb.modality_key = b.modality_key
              AND cb.source_table = b.source_table
              AND cb.column_value = b.column_value
            WHERE a.value <> 0 AND ca.column_is_gene = 0 AND cb.column_is_gene = 0"""
    ):
        matches[(modality, table, other, gene_id)].add(column_value)

    n_values: dict[tuple[str, int], int] = {
        (table, gene_id): n
        for table, gene_id, n in conn.execute(
            """SELECT source_table, central_gene_id, COUNT(*)
                 FROM overview_matrix_expanded_cells GROUP BY 1, 2"""
        )
    }
    rows: list[tuple[str, str, str, int, str, str]] = []
    genes_by_pair: dict[tuple[str, str], set[int]] = defaultdict(set)
    for (modality, table, other, gene_id), columns in matches.items():
        smaller = min(n_values[(table, gene_id)], n_values[(other, gene_id)])
        if len(columns) < max(_SHARED_MIN_VALUES, _SHARED_MIN_FRACTION * smaller):
            continue
        genes_by_pair[(table, other)].add(gene_id)
        rows.extend(
            (modality, table, column, gene_id, other, labels.get(other, other))
            for column in columns
        )
    conn.executemany(
        "INSERT INTO overview_matrix_shared_cells (modality_key, source_table, "
        "column_value, central_gene_id, shared_with_table, shared_with_label) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    for (table, other), genes in sorted(genes_by_pair.items()):
        if table > other:
            continue
        click.echo(
            f"  Overview matrix: {table} and {other} share values for "
            f"{len(genes)} gene(s)"
        )
        source = evidence_sources.get(table)
        if source is None or source != evidence_sources.get(other):
            log.warning(
                "overview matrix: %s and %s share values for %d gene(s) but declare "
                "no common evidence_source, so they would count as independent",
                table,
                other,
                len(genes),
            )


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
    significant_only: dict[str, list[str]] | None = None,
    species: str | None = None,
    effect_column: str | None = None,
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

    if phenotype_column and metric == "signed_neglog_p":
        # LONG with a direction — config validation requires both columns.
        return _materialize_long_signed_axis(
            conn,
            modality_key=modality_key,
            table_name=table_name,
            source_label=source_label,
            base_table=base_table,
            link_table=link_table,
            phenotype_column=phenotype_column,
            pvalue_column=pvalue_column or "",
            effect_column=_split_columns(effect_column)[0],
            metric_domain=metric_domain,
            src_schema=src_schema,
        )

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
        significant_only=significant_only,
        species=species,
    )


def _collate_source(
    conn: sqlite3.Connection,
    *,
    collate_group: str,
    table_name: str,
    dataset: str | None,
    medium_label: str | None,
    short_label: str | None,
    link_tables_raw: str | None,
    pvalue_column: str | None,
    fdr_column: str | None,
    effect_column: str | None,
    significant_only: dict[str, list[str]] | None,
    species: str | None,
    src_schema: str,
) -> tuple[CollateSource, dict[object, list[int]], str] | None:
    """Resolve one gene-target table into a collated-view source, or None.

    Uses the same column resolution as the expanded view (`_materialize_expansion`)
    so both views read a table identically.
    """
    log = get_sspsygene_logger()
    base_table = sanitize_identifier(table_name)
    perturbed_links = parse_link_tables_for_direction(link_tables_raw or "", "perturbed")
    target_link = target_link_for(link_tables_raw)
    if not perturbed_links or target_link is None:
        return None
    if not conn.execute(
        f"SELECT 1 FROM {src_schema}.sqlite_master WHERE type = 'table' AND name = ?",
        (target_link,),
    ).fetchone():
        log.warning(
            "overview matrix: %s target link table %s is missing; not collated",
            table_name,
            target_link,
        )
        return None
    columns = _table_columns(conn, base_table, src_schema)
    source_columns = _resolve_source_columns(link_tables_raw, columns)
    group_column = source_columns["perturbed"]
    if not group_column or not source_columns["target"]:
        return None
    pvalue_cols = _split_columns(pvalue_column)
    fdr_cols = _split_columns(fdr_column)
    p_col = pvalue_cols[0] if pvalue_cols else (fdr_cols[0] if fdr_cols else None)
    fdr_col = fdr_cols[0] if fdr_cols else (pvalue_cols[0] if pvalue_cols else None)
    if p_col is None or fdr_col is None:
        return None
    effect_cols = _split_columns(effect_column)
    effect_col = effect_cols[0] if effect_cols and effect_cols[0] in columns else None

    context_columns: list[str] | None = None
    library_gene_ids: set[int] = set()
    context_expr = "''"
    if significant_only is not None:
        context_columns = list(significant_only.get("context_columns") or [])
        expr = _context_expr(context_columns, columns)
        if expr is None:
            log.warning(
                "overview matrix: %s significant_only context columns %s missing; "
                "collated view treats it as a full table",
                table_name,
                context_columns,
            )
            context_columns = None
        else:
            context_expr = expr
            library_gene_ids, _ = _resolve_perturbation_values(
                conn,
                list(significant_only.get("tested_perturbations") or []),
                species,
                src_schema,
            )

    group_genes = _group_to_genes(
        conn, base_table, perturbed_links[0], group_column, src_schema
    )
    study_label = _study_label(medium_label, short_label, table_name)
    source = CollateSource(
        collate_group=collate_group,
        table_name=table_name,
        study=dataset or table_name,
        study_label=study_label,
        base_table=base_table,
        group_column=group_column,
        perturbed_link=perturbed_links[0],
        target_link=target_link,
        p_col=p_col,
        fdr_col=fdr_col,
        effect_col=effect_col,
        context_columns=context_columns,
        library_gene_ids=frozenset(library_gene_ids),
    )
    return source, group_genes, context_expr


def materialize_overview_matrix(
    conn: sqlite3.Connection,
    *,
    no_index: bool = False,
    min_groups: int = ELIGIBILITY_MIN_GROUPS,
    src_schema: str = "main",
    panel_gene_ids: set[int] | None = None,
    all_destinations: bool = False,
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

    `all_destinations` drops the prod-only input filter (below) so every flagged
    table in the source DB contributes, dev- and int-only ones included (#241).
    That file is dev's wrangler preview and is never promoted.
    """
    min_groups = max(1, min_groups)
    scope = "all" if all_destinations else "prod"
    _create_schema(conn)
    _create_panel_filter(conn, panel_gene_ids, src_schema)

    modality_keys, assay_to_modalities = _load_modalities(conn, src_schema)
    if not modality_keys:
        _write_info(conn, min_groups, [], panel_gene_ids, src_schema, scope)
        conn.commit()
        return

    # Prod-labelled inputs only (#225), whichever main DB we are reading. The
    # overview tables record contributing table names (expansions.source_tables,
    # expanded_columns/_cells.source_table, info.expanded_source_tables), so a
    # run against dev's superset would carry int-only names into every copy.
    # Restricting to prod makes the file destination-independent, which is what
    # lets it be built once on dev and copied verbatim to prod and int.
    # Guarded on the table existing so pre-#225 DBs and the in-memory test
    # fixtures still materialize every flagged table. Skipped entirely for the
    # all-destinations build (#241), which stays on dev.
    prod_clause = ""
    if not all_destinations and conn.execute(
        f"SELECT 1 FROM {src_schema}.sqlite_master "
        f"WHERE type='table' AND name='dataset_destinations'"
    ).fetchone():
        prod_clause = (
            f" AND table_name IN (SELECT table_name FROM "
            f"{src_schema}.dataset_destinations WHERE destination = 'prod')"
        )
    # Columns newer than some source DBs (and than the test fixtures) are read
    # as NULL when absent, so an old dataset DB still materializes.
    dt_columns = _table_columns(conn, "data_tables", src_schema)
    optional = ", ".join(
        col if col in dt_columns else f"NULL AS {col}"
        for col in (
            "significant_only",
            "gene_species",
            "dataset",
            "effect_column",
            "medium_label",
            "evidence_source",
            "overview_matrix_phenotype_terms",
        )
    )
    source_rows = conn.execute(
        f"""SELECT table_name, assay, pvalue_column, fdr_column, link_tables,
                   short_label,
                   overview_matrix_phenotype_column,
                   overview_matrix_phenotype_columns,
                   overview_matrix_metric, overview_matrix_metric_domain,
                   {optional}
             FROM {src_schema}.data_tables
            WHERE include_in_overview_matrix = 1{prod_clause}"""
    ).fetchall()

    expanded_source_tables: list[str] = []
    perturbed_link_tables: list[str] = []
    collate_sources: list[CollateSource] = []
    phenotype_sources: list[PhenotypeSource] = []
    study_labels: dict[str, str] = {}
    evidence_sources: dict[str, str] = {}
    collate_group_genes: dict[str, dict[object, list[int]]] = {}
    collate_context_exprs: dict[str, str] = {}
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
        significant_only_raw,
        gene_species,
        dataset,
        effect_column,
        medium_label,
        evidence_source,
        phenotype_terms_raw,
    ) in source_rows:
        modality_keys_for_table = _modality_keys_for(assay, assay_to_modalities)
        if not modality_keys_for_table:
            continue
        modality_key = modality_keys_for_table[0]
        study_labels[table_name] = _study_label(medium_label, short_label, table_name)
        if evidence_source:
            evidence_sources[table_name] = evidence_source

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
        try:
            significant_only = (
                json.loads(significant_only_raw) if significant_only_raw else None
            )
        except (TypeError, ValueError):
            significant_only = None

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
            significant_only=significant_only,
            species=gene_species,
            effect_column=effect_column,
        )
        if modality_key in COLLATE_GROUPS and not phenotype_column and not phenotype_columns:
            prepared = _collate_source(
                conn,
                collate_group=COLLATE_GROUPS[modality_key],
                table_name=table_name,
                dataset=evidence_source or dataset,
                medium_label=medium_label,
                short_label=short_label,
                link_tables_raw=link_tables_raw,
                pvalue_column=pvalue_column,
                fdr_column=fdr_column,
                effect_column=effect_column,
                significant_only=significant_only,
                species=gene_species,
                src_schema=src_schema,
            )
            if prepared is not None:
                collate_source, group_genes, context_expr = prepared
                collate_sources.append(collate_source)
                collate_group_genes[table_name] = group_genes
                collate_context_exprs[table_name] = context_expr
        if phenotype_terms_raw:
            source = _phenotype_source(
                conn,
                table_name=table_name,
                study=evidence_source or dataset or table_name,
                study_label=study_labels[table_name],
                terms_raw=phenotype_terms_raw,
                link_tables_raw=link_tables_raw,
                phenotype_column=phenotype_column,
                pvalue_column=pvalue_column,
                fdr_column=fdr_column,
                effect_column=effect_column,
                src_schema=src_schema,
            )
            if source is not None:
                phenotype_sources.append(source)
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

    materialize_shared_cells(conn, study_labels, evidence_sources)
    materialize_collated(
        conn, collate_sources, collate_group_genes, collate_context_exprs, src_schema
    )
    materialize_phenotype_collated(conn, phenotype_sources, src_schema, _PANEL_TABLE)

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
        conn, min_groups, expanded_source_tables, panel_gene_ids, src_schema,
        scope,
    )
    conn.commit()


def _write_info(
    conn: sqlite3.Connection,
    min_groups: int,
    expanded_source_tables: list[str],
    panel_gene_ids: set[int] | None = None,
    src_schema: str = "main",
    scope: str = "prod",
) -> None:
    rows = [
        ("schema_version", SCHEMA_VERSION),
        # "prod": prod-labelled inputs only, copied to every instance. "all":
        # dev's preview including dev/int-only tables (#241).
        ("destination_scope", scope),
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
