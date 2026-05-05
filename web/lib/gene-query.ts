import type Database from "better-sqlite3";

export const ROW_LIMIT = 10;

export type ApiSortMode = "asc" | "desc" | "asc_abs" | "desc_abs";

export interface OrderBySpec {
  column: string;      // already sanitized column name
  mode: ApiSortMode;
  tableAlias?: string; // e.g. "b"
}

export function buildOrderByClause(spec: OrderBySpec | null): string {
  if (!spec) return "";
  const { column, mode, tableAlias } = spec;
  const prefix = tableAlias ? `${tableAlias}.` : "";
  const isAbs = mode === "asc_abs" || mode === "desc_abs";
  const isAsc = mode === "asc" || mode === "asc_abs";
  const dir = isAsc ? "ASC" : "DESC";
  const nulls = isAsc ? "NULLS LAST" : "NULLS FIRST";
  const expr = isAbs ? `ABS(${prefix}${column})` : `${prefix}${column}`;
  return `ORDER BY ${expr} ${dir} ${nulls}`;
}

/**
 * Validate a sort column against a set of allowed display columns.
 * Returns the sanitized column name, or null if invalid.
 */
export function validateSortColumn(
  sortBy: string | undefined | null,
  displayColumns: string[],
): string | null {
  if (!sortBy) return null;
  const colSet = new Set(displayColumns);
  if (!colSet.has(sortBy)) return null;
  return sanitizeIdentifier(sortBy);
}

/**
 * Pick the default sort column for a per-dataset table.
 * Prefers FDR over raw p-value (FDR is multiple-testing-corrected). For
 * comma-separated specs, uses the first listed column. Returns null when
 * neither column is configured — caller should skip ORDER BY in that case
 * so insertion order is preserved.
 */
export function pickDefaultSortColumn(t: {
  fdr_column: string | null;
  pvalue_column: string | null;
}): string | null {
  const src = t.fdr_column ?? t.pvalue_column;
  if (!src) return null;
  const first = src.split(",")[0]?.trim();
  return first || null;
}

export function sanitizeIdentifier(id: string): string {
  if (!/^\w+$/.test(id)) throw new Error(`Invalid identifier: ${id}`);
  return id;
}

/**
 * Build a WHERE-clause fragment from a per-column filter map.
 *
 * Scalar columns accept an optional leading comparison operator
 * (`>`, `>=`, `<`, `<=`, `=`, `!=`) followed by a number; without an operator,
 * a numeric value falls back to substring match on the text representation
 * (so users can still type partial values like "1.2" and see matches).
 * Non-scalar columns always use case-insensitive substring (LIKE %v%).
 *
 * Column names are validated against `displayColumns` and re-sanitized via
 * `sanitizeIdentifier`. Values are bound as parameters.
 *
 * Returns "" + [] when there are no usable filters.
 */
export function buildFilterClause(opts: {
  filters: Record<string, string> | null | undefined;
  displayColumns: string[];
  scalarColumns: Set<string>;
  tableAlias?: string;
}): { clause: string; params: (string | number)[] } {
  const { filters, displayColumns, scalarColumns, tableAlias } = opts;
  if (!filters) return { clause: "", params: [] };

  const allowed = new Set(displayColumns);
  const prefix = tableAlias ? `${tableAlias}.` : "";
  const conditions: string[] = [];
  const params: (string | number)[] = [];

  // Numbers: optional sign, then either digits-with-optional-fraction
  // (`12`, `12.3`) or a leading-dot fraction (`.03`); optional exponent.
  const cmpRe = /^\s*(>=|<=|!=|>|<|=)\s*(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*$/;

  for (const [rawCol, rawVal] of Object.entries(filters)) {
    if (typeof rawVal !== "string") continue;
    const val = rawVal.trim();
    if (!val) continue;
    if (!allowed.has(rawCol)) continue;
    let col: string;
    try {
      col = sanitizeIdentifier(rawCol);
    } catch {
      continue;
    }
    const ref = `${prefix}${col}`;

    if (scalarColumns.has(col)) {
      const m = cmpRe.exec(val);
      if (m) {
        const op = m[1] === "=" ? "=" : m[1];
        const num = Number(m[2]);
        if (Number.isFinite(num)) {
          conditions.push(`${ref} ${op} ?`);
          params.push(num);
          continue;
        }
      }
      // No operator (or unparseable) — substring match against text repr.
      conditions.push(`CAST(${ref} AS TEXT) LIKE ? ESCAPE '\\'`);
      params.push(`%${escapeLike(val)}%`);
    } else {
      conditions.push(`${ref} LIKE ? ESCAPE '\\' COLLATE NOCASE`);
      params.push(`%${escapeLike(val)}%`);
    }
  }

  if (conditions.length === 0) return { clause: "", params: [] };
  return { clause: conditions.join(" AND "), params };
}

function escapeLike(s: string): string {
  return s.replace(/[\\%_]/g, (c) => `\\${c}`);
}

export type SearchDirection = "target" | "perturbed";

/**
 * Sentinel central_gene_id meaning "match every kind='control' gene".
 * Used by the home page search to let users query all control genes
 * with a single CONTROL pseudo-suggestion instead of picking one of
 * NonTarget1 / SafeTarget / GFP / … individually. Negative because
 * real central_gene_id rows are non-negative auto-increment ints.
 */
export const ALL_CONTROLS_SENTINEL_ID = -1;

/**
 * Parse link table names for a specific search direction. Mirrors the Python
 * helper of the same name in processing/src/processing/combined_pvalues.py.
 *
 * Each link-table entry has the form "col:lt:direction" where direction is
 * the literal string "perturbed" or "target". An entry contributes to a query
 * iff its direction matches the requested one.
 */
export function parseLinkTablesForDirection(
  linkTablesRaw: string,
  direction: SearchDirection,
): string[] {
  return (linkTablesRaw || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((entry) => {
      const parts = entry.split(":");
      return {
        name: parts.length >= 2 ? sanitizeIdentifier(parts[1]) : null,
        direction: parts[2] ?? null,
      };
    })
    .filter((e): e is { name: string; direction: string } =>
      e.name !== null && e.direction === direction,
    )
    .map((e) => e.name);
}

/**
 * Mirror the Python `normalize_column_name` (table_to_process_config.py):
 * lowercase, then replace any non-[a-z0-9_] run with a single underscore.
 * data_tables.display_columns is always normalized form, so anything we
 * compare against display_columns must be normalized too.
 */
function toSqlFriendlyColumn(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9_]+/g, "_");
}

/**
 * Return the source-column names whose link-table entry has the given
 * direction. Used by data-table renderers to decide whether a clicked
 * gene cell should search as perturbed or target. Mirrors
 * parseLinkTablesForDirection but pulls field 0 (column) instead of 1,
 * and normalizes via toSqlFriendlyColumn so the result matches what's
 * in data_tables.display_columns / data_tables.gene_columns (e.g.
 * `gene-symbol` from YAML → `gene_symbol`).
 */
export function parseSourceColumnsForDirection(
  linkTablesRaw: string,
  direction: SearchDirection,
): string[] {
  return (linkTablesRaw || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((entry) => {
      const parts = entry.split(":");
      return {
        column: parts[0] ? toSqlFriendlyColumn(parts[0]) : null,
        direction: parts[2] ?? null,
      };
    })
    .filter((e): e is { column: string; direction: string } =>
      e.column !== null && e.direction === direction,
    )
    .map((e) => e.column);
}

export function parseDisplayColumns(raw: string): string[] {
  return (raw || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map(sanitizeIdentifier);
}

/**
 * Build the SELECT columns and FROM...WHERE clause for a gene query.
 *
 * The pair-search form may have 0, 1, or 2 of perturbedCentralGeneId /
 * targetCentralGeneId set. For each set side, the table must have a
 * link-table entry with the matching direction; otherwise this returns null
 * (caller skips the table). When both sides are set, results are the
 * INTERSECT of both link-table lookups.
 *
 * Returns null if no usable subquery can be built (no gene specified, or the
 * table doesn't carry the required direction).
 */
export function buildGeneQuery(opts: {
  baseTable: string;
  displayCols: string[];
  linkTablesRaw: string;
  perturbedCentralGeneId?: number | null;
  targetCentralGeneId?: number | null;
}): { selectCols: string; fromAndWhere: string; params: string[] } | null {
  const { baseTable, displayCols, linkTablesRaw } = opts;
  const selectCols = displayCols.map((c) => `b.${c}`).join(", ");
  const params: string[] = [];

  const perturbedLTs = parseLinkTablesForDirection(linkTablesRaw || "", "perturbed");
  const targetLTs = parseLinkTablesForDirection(linkTablesRaw || "", "target");

  const subqueries: string[] = [];
  // Sentinel id means "all control genes" — expand to a kind='control'
  // subquery instead of an exact-match `central_gene_id = ?`.
  const allControls = `SELECT id FROM central_gene WHERE kind = 'control'`;
  if (opts.perturbedCentralGeneId) {
    if (perturbedLTs.length !== 1) return null;
    if (opts.perturbedCentralGeneId === ALL_CONTROLS_SENTINEL_ID) {
      subqueries.push(
        `SELECT id FROM ${perturbedLTs[0]} WHERE central_gene_id IN (${allControls})`,
      );
    } else {
      subqueries.push(`SELECT id FROM ${perturbedLTs[0]} WHERE central_gene_id = ?`);
      params.push(String(opts.perturbedCentralGeneId));
    }
  }
  if (opts.targetCentralGeneId) {
    if (targetLTs.length !== 1) return null;
    if (opts.targetCentralGeneId === ALL_CONTROLS_SENTINEL_ID) {
      subqueries.push(
        `SELECT id FROM ${targetLTs[0]} WHERE central_gene_id IN (${allControls})`,
      );
    } else {
      subqueries.push(`SELECT id FROM ${targetLTs[0]} WHERE central_gene_id = ?`);
      params.push(String(opts.targetCentralGeneId));
    }
  }

  if (subqueries.length === 0) return null;

  const idSubquery = subqueries.length === 1
    ? subqueries[0]
    : subqueries.join(" INTERSECT ");
  const fromAndWhere = `FROM ${baseTable} b WHERE b.id IN (${idSubquery})`;
  return { selectCols, fromAndWhere, params };
}

/**
 * Fetch the first page of results using the fetch+1 pattern.
 * Only runs the expensive COUNT query when there are more rows than ROW_LIMIT.
 * Returns null if there are no matching rows.
 */
export function queryFirstPage(
  db: Database.Database,
  selectCols: string,
  fromAndWhere: string,
  params: string[],
  orderBy?: string,
): { rows: Record<string, unknown>[]; totalRows: number } | null {
  const orderClause = orderBy ?? "";
  const dataSql = `SELECT DISTINCT ${selectCols} ${fromAndWhere} ${orderClause} LIMIT ${ROW_LIMIT + 1}`;
  const allRows = db.prepare(dataSql).all(...params) as Record<string, unknown>[];

  if (allRows.length === 0) return null;

  const hasMore = allRows.length > ROW_LIMIT;
  const rows = hasMore ? allRows.slice(0, ROW_LIMIT) : allRows;

  let totalRows: number;
  if (hasMore) {
    const countSql = `SELECT COUNT(*) as cnt FROM (SELECT DISTINCT ${selectCols} ${fromAndWhere})`;
    totalRows = (db.prepare(countSql).get(...params) as { cnt: number }).cnt;
  } else {
    totalRows = rows.length;
  }

  return { rows, totalRows };
}

/**
 * Fetch a specific page of results using OFFSET-based pagination.
 * Always runs a COUNT query since the caller already knows there are multiple pages.
 */
export function queryPage(
  db: Database.Database,
  selectCols: string,
  fromAndWhere: string,
  params: string[],
  page: number,
  orderBy?: string,
): { rows: Record<string, unknown>[]; totalRows: number; page: number; totalPages: number } {
  const countSql = `SELECT COUNT(*) as cnt FROM (SELECT DISTINCT ${selectCols} ${fromAndWhere})`;
  const totalRows = (db.prepare(countSql).get(...params) as { cnt: number }).cnt;
  const totalPages = Math.max(1, Math.ceil(totalRows / ROW_LIMIT));

  const effectivePage = Math.min(page, totalPages);
  const offset = (effectivePage - 1) * ROW_LIMIT;

  const orderClause = orderBy ?? "";
  const dataSql = `SELECT DISTINCT ${selectCols} ${fromAndWhere} ${orderClause} LIMIT ${ROW_LIMIT} OFFSET ${offset}`;
  const rows = db.prepare(dataSql).all(...params) as Record<string, unknown>[];

  return { rows, totalRows, page: effectivePage, totalPages };
}
