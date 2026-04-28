import type Database from "better-sqlite3";

/**
 * Replace Ensembl IDs (ENSG, ENSMUSG, ENSDARG) with the corresponding gene
 * symbol, using the pre-computed `ensembl_to_symbol` table populated at
 * load-db time. Per Max's 2026-04-28 follow-up on #75: never display ENSG
 * IDs when a symbol is known; fall back to the raw ENSG when no mapping
 * exists.
 *
 * The cache is module-level so we only hit SQLite once per process. Tests or
 * load-db retries that swap the database in place will need to call
 * `clearEnsemblSymbolCache()` (or restart the process).
 */

const ENSG_PATTERN_GLOBAL = /\b(ENS(?:MUS|DAR)?G\d+)(?:\.\d+)?\b/g;

let cachedMap: Map<string, string> | null = null;

export function clearEnsemblSymbolCache(): void {
  cachedMap = null;
}

export function getEnsemblSymbolMap(
  db: Database.Database,
): Map<string, string> {
  // Only memoize *populated* maps. An empty result usually means we hit the
  // DB before load-db built the table; caching it would freeze the API in
  // pass-through mode for the lifetime of the process. Re-querying until we
  // see a non-empty table is cheap (one SELECT) and self-heals after rebuild.
  if (cachedMap && cachedMap.size > 0) return cachedMap;
  try {
    const rows = db
      .prepare("SELECT ensembl_id, symbol FROM ensembl_to_symbol")
      .all() as Array<{ ensembl_id: string; symbol: string }>;
    if (rows.length > 0) {
      cachedMap = new Map(rows.map((r) => [r.ensembl_id, r.symbol]));
      return cachedMap;
    }
  } catch {
    // Table may not exist yet (running against an older DB) — fall through.
  }
  return new Map();
}

/**
 * Replace any Ensembl ID occurrence inside a single string (works for both
 * standalone IDs and IDs embedded in longer text). Strips any version suffix
 * (`.1`, `.12`, etc.) when looking up.
 */
export function replaceEnsgsInString(
  text: string,
  symbolMap: Map<string, string>,
): string {
  if (!text || symbolMap.size === 0) return text;
  ENSG_PATTERN_GLOBAL.lastIndex = 0;
  if (!ENSG_PATTERN_GLOBAL.test(text)) return text;
  ENSG_PATTERN_GLOBAL.lastIndex = 0;
  return text.replace(ENSG_PATTERN_GLOBAL, (full, id) => {
    return symbolMap.get(id) ?? full;
  });
}

/** Apply the replacement to every string-valued cell in a row. */
export function resolveEnsgsInRow<T extends Record<string, unknown>>(
  row: T,
  symbolMap: Map<string, string>,
): T {
  if (symbolMap.size === 0) return row;
  let mutated: Record<string, unknown> | null = null;
  for (const k of Object.keys(row)) {
    const v = row[k];
    if (typeof v !== "string") continue;
    const replaced = replaceEnsgsInString(v, symbolMap);
    if (replaced === v) continue;
    if (!mutated) mutated = { ...row };
    mutated[k] = replaced;
  }
  return (mutated ?? row) as T;
}

export function resolveEnsgsInRows<T extends Record<string, unknown>>(
  rows: T[],
  symbolMap: Map<string, string>,
): T[] {
  if (symbolMap.size === 0 || rows.length === 0) return rows;
  return rows.map((r) => resolveEnsgsInRow(r, symbolMap));
}
