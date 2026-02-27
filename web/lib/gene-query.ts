import type Database from "better-sqlite3";

export const ROW_LIMIT = 25;

export function sanitizeIdentifier(id: string): string {
  if (!/^\w+$/.test(id)) throw new Error(`Invalid identifier: ${id}`);
  return id;
}

/**
 * Parse link table names from the data_tables.link_tables column,
 * skipping perturbed link tables in tables that have both perturbed
 * and target mappings (perturbed genes appear in every row they were
 * knocked down in, so their p-values don't represent evidence about
 * the perturbed gene itself).
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
 * General mode: pass centralGeneId. Link tables are combined with UNION.
 * Pair mode: pass perturbedCentralGeneId and/or targetCentralGeneId.
 *   Link tables are parsed for isPerturbed/isTarget flags and combined with INTERSECT.
 *
 * Returns null if the table cannot be queried (no link tables, or pair mode
 * with missing perturbed/target link tables).
 */
export function buildGeneQuery(opts: {
  baseTable: string;
  displayCols: string[];
  linkTablesRaw: string;
  centralGeneId?: number;
  perturbedCentralGeneId?: number | null;
  targetCentralGeneId?: number | null;
}): { selectCols: string; fromAndWhere: string; params: string[] } | null {
  const { baseTable, displayCols, linkTablesRaw } = opts;
  const selectCols = displayCols.map((c) => `b.${c}`).join(", ");
  const params: string[] = [];
  const isPairMode = opts.centralGeneId === undefined;

  if (!isPairMode) {
    // General mode: extract link table names, combine with UNION
    const linkTables = (linkTablesRaw || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map((entry) => {
        const parts = entry.split(":");
        return sanitizeIdentifier(parts.length >= 2 ? parts[1] : parts[0]);
      });

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
): { rows: Record<string, unknown>[]; totalRows: number } | null {
  const dataSql = `SELECT DISTINCT ${selectCols} ${fromAndWhere} LIMIT ${ROW_LIMIT + 1}`;
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
): { rows: Record<string, unknown>[]; totalRows: number; page: number; totalPages: number } {
  const countSql = `SELECT COUNT(*) as cnt FROM (SELECT DISTINCT ${selectCols} ${fromAndWhere})`;
  const totalRows = (db.prepare(countSql).get(...params) as { cnt: number }).cnt;
  const totalPages = Math.max(1, Math.ceil(totalRows / ROW_LIMIT));

  const effectivePage = Math.min(page, totalPages);
  const offset = (effectivePage - 1) * ROW_LIMIT;

  const dataSql = `SELECT DISTINCT ${selectCols} ${fromAndWhere} LIMIT ${ROW_LIMIT} OFFSET ${offset}`;
  const rows = db.prepare(dataSql).all(...params) as Record<string, unknown>[];

  return { rows, totalRows, page: effectivePage, totalPages };
}
