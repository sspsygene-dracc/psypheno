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
 * Legacy "drop perturbed only when both sides exist" parser. Used by callers
 * that pre-date the direction-aware flip toggle (#65 / #66) — currently only
 * /api/significant-rows. New code should use parseLinkTablesForDirection.
 */
export function parseNonPerturbedLinkTables(linkTablesRaw: string): string[] {
  const entries = (linkTablesRaw || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((entry) => {
      const parts = entry.split(":");
      const name = sanitizeIdentifier(parts.length >= 2 ? parts[1] : parts[0]);
      const isPerturbed = parts.length >= 3 && parts[2] === "1";
      return { name, isPerturbed };
    });

  const hasPerturbed = entries.some((e) => e.isPerturbed);
  const hasNonPerturbed = entries.some((e) => !e.isPerturbed);

  if (hasPerturbed && hasNonPerturbed) {
    return entries.filter((e) => !e.isPerturbed).map((e) => e.name);
  }
  return entries.map((e) => e.name);
}

/**
 * Parse link table names for a specific search direction. Mirrors the Python
 * helper of the same name in processing/src/processing/combined_pvalues.py.
 *
 * For each link-table entry "col:lt:is_perturbed:is_target":
 *   target    -> include if is_target == 1 OR (both flags 0)
 *   perturbed -> include if is_perturbed == 1 OR (both flags 0)
 *
 * Generic gene tables (both flags 0) appear in both directions; pure-direction
 * link tables only in the matching mode; mixed tables contribute only the
 * matching side.
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
        name: sanitizeIdentifier(parts.length >= 2 ? parts[1] : parts[0]),
        isPerturbed: parts[2] === "1",
        isTarget: parts[3] === "1",
      };
    })
    .filter((e) => {
      const isGeneric = !e.isPerturbed && !e.isTarget;
      return direction === "target"
        ? e.isTarget || isGeneric
        : e.isPerturbed || isGeneric;
    })
    .map((e) => e.name);
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
 * General mode: pass centralGeneId and a `direction` ("target" or
 *   "perturbed"). Link tables are filtered by direction and combined with UNION.
 * Pair mode: pass perturbedCentralGeneId and/or targetCentralGeneId.
 *   Link tables are parsed for isPerturbed/isTarget flags and combined with INTERSECT.
 *
 * Returns null if the table cannot be queried (no link tables for the
 * requested direction, or pair mode with missing perturbed/target link tables).
 */
export function buildGeneQuery(opts: {
  baseTable: string;
  displayCols: string[];
  linkTablesRaw: string;
  centralGeneId?: number;
  direction?: SearchDirection;
  perturbedCentralGeneId?: number | null;
  targetCentralGeneId?: number | null;
}): { selectCols: string; fromAndWhere: string; params: string[] } | null {
  const { baseTable, displayCols, linkTablesRaw } = opts;
  const selectCols = displayCols.map((c) => `b.${c}`).join(", ");
  const params: string[] = [];
  const isPairMode = opts.centralGeneId === undefined;

  if (!isPairMode) {
    // General mode: filter link tables by direction, combine with UNION.
    const direction: SearchDirection = opts.direction ?? "target";
    const linkTables = parseLinkTablesForDirection(linkTablesRaw || "", direction);

    if (linkTables.length === 0) return null;

    const subqueries = linkTables.map((lt) => {
      params.push(String(opts.centralGeneId));
      return `SELECT id FROM ${lt} WHERE central_gene_id = ?`;
    });
    const idSubquery = subqueries.length === 1
      ? subqueries[0]
      : subqueries.join(" UNION ");
    const fromAndWhere = `FROM ${baseTable} b WHERE b.id IN (${idSubquery})`;
    return { selectCols, fromAndWhere, params };
  } else {
    // Pair mode: parse link tables with isPerturbed/isTarget flags
    const parsed = (linkTablesRaw || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map((entry) => {
        const parts = entry.split(":");
        return {
          linkTable: sanitizeIdentifier(parts[1] ?? parts[0] ?? ""),
          isPerturbed: parts[2] === "1",
          isTarget: parts[3] === "1",
        };
      });

    const perturbedLTs = parsed.filter((p) => p.isPerturbed).map((p) => p.linkTable);
    const targetLTs = parsed.filter((p) => p.isTarget).map((p) => p.linkTable);
    if (perturbedLTs.length !== 1 || targetLTs.length !== 1) return null;

    const subqueries: string[] = [];
    if (opts.perturbedCentralGeneId) {
      subqueries.push(`SELECT id FROM ${perturbedLTs[0]} WHERE central_gene_id = ?`);
      params.push(String(opts.perturbedCentralGeneId));
    }
    if (opts.targetCentralGeneId) {
      subqueries.push(`SELECT id FROM ${targetLTs[0]} WHERE central_gene_id = ?`);
      params.push(String(opts.targetCentralGeneId));
    }

    if (subqueries.length === 0) return null;

    const idSubquery = subqueries.length === 1
      ? subqueries[0]
      : subqueries.join(" INTERSECT ");
    const fromAndWhere = `FROM ${baseTable} b WHERE b.id IN (${idSubquery})`;
    return { selectCols, fromAndWhere, params };
  }
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
