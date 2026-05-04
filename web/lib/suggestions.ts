import { getDb } from "@/lib/db";
import { parseLinkTablesForDirection, type SearchDirection } from "@/lib/gene-query";
import { SearchSuggestion, type CentralGeneKind } from "@/state/SearchSuggestion";
import type Database from "better-sqlite3";

interface GeneSuggestionRow {
  id: number;
  human_symbol: string | null;
  mouse_symbols: string | null;
  human_synonyms: string | null;
  mouse_synonyms: string | null;
  dataset_count: number;
  kind: CentralGeneKind;
}

// Typing `control` (or `controls`) in the search box is a shorthand for
// "show me every kind='control' entry across all datasets" — useful for
// sanity-checking volcanoes and finding what each Perturb-seq study used
// as its negative control. Case-insensitive; trimmed.
const CONTROL_KEYWORDS = new Set(["control", "controls"]);

type StmtTriple = {
  stmtHuman: Database.Statement;
  stmtMouse: Database.Statement;
  stmtSynonym: Database.Statement;
};

// Per-direction prepared statements, cached on first use. The directional
// subquery is baked into the SQL because it's derived from data_tables and
// changes only when the DB is rebuilt (which swaps the connection identity).
let stmtsDb: Database.Database | null = null;
let stmtsAll: StmtTriple | null = null;
let stmtsPerturbed: StmtTriple | null = null;
let stmtsTarget: StmtTriple | null = null;

// Materialize a TEMP table containing the distinct central_gene_ids that
// appear in any link table tagged with the given direction, then return its
// name. The temp DB is writable even on a read-only main connection, and
// querying a single PK-indexed temp table beats re-running the union of N
// link-table scans on every keystroke. Returns null when no link tables
// match the direction (autocomplete should yield nothing).
function materializeDirectionalIds(
  db: Database.Database,
  direction: SearchDirection,
): string | null {
  const rows = db
    .prepare(`SELECT link_tables FROM data_tables`)
    .all() as Array<{ link_tables: string | null }>;
  const linkTables = new Set<string>();
  for (const r of rows) {
    if (!r.link_tables) continue;
    for (const lt of parseLinkTablesForDirection(r.link_tables, direction)) {
      linkTables.add(lt);
    }
  }
  if (linkTables.size === 0) return null;
  const tempName = `_autocomplete_${direction}_ids`;
  db.exec(`DROP TABLE IF EXISTS temp.${tempName}`);
  db.exec(
    `CREATE TEMP TABLE ${tempName} (central_gene_id INTEGER PRIMARY KEY)`,
  );
  // Table identifiers can't be bound, so concatenate. Values come from
  // sanitizeIdentifier inside parseLinkTablesForDirection.
  for (const lt of linkTables) {
    db.exec(
      `INSERT OR IGNORE INTO temp.${tempName} (central_gene_id) ` +
        `SELECT central_gene_id FROM ${lt}`,
    );
  }
  return tempName;
}

function prepareTriple(
  db: Database.Database,
  directionalIdsTable: string | null,
): StmtTriple {
  const filterDirect = directionalIdsTable
    ? `AND id IN (SELECT central_gene_id FROM temp.${directionalIdsTable})`
    : "";
  const filterJoined = directionalIdsTable
    ? `AND cg.id IN (SELECT central_gene_id FROM temp.${directionalIdsTable})`
    : "";

  const stmtHuman = db.prepare(`
    SELECT id, human_symbol, mouse_symbols, human_synonyms, mouse_synonyms,
           num_datasets AS dataset_count, kind
    FROM central_gene
    WHERE human_symbol LIKE ? COLLATE NOCASE
    ${filterDirect}
    ORDER BY num_datasets DESC, human_symbol ASC
    LIMIT ?
  `);

  const stmtMouse = db.prepare(`
    SELECT cg.id AS id, cg.human_symbol AS human_symbol,
           cg.mouse_symbols AS mouse_symbols, cg.human_synonyms AS human_synonyms,
           cg.mouse_synonyms AS mouse_synonyms, cg.num_datasets AS dataset_count,
           cg.kind AS kind
    FROM extra_mouse_symbols ms
    JOIN central_gene cg ON cg.id = ms.central_gene_id
    WHERE ms.symbol LIKE ? COLLATE NOCASE
    ${filterJoined}
    GROUP BY cg.id
    ORDER BY cg.num_datasets DESC, cg.human_symbol ASC
    LIMIT ?
  `);

  const stmtSynonym = db.prepare(`
    SELECT cg.id AS id, cg.human_symbol AS human_symbol,
           cg.mouse_symbols AS mouse_symbols, cg.human_synonyms AS human_synonyms,
           cg.mouse_synonyms AS mouse_synonyms, cg.num_datasets AS dataset_count,
           cg.kind AS kind
    FROM extra_gene_synonyms gs
    JOIN central_gene cg ON cg.id = gs.central_gene_id
    WHERE gs.synonym LIKE ? COLLATE NOCASE
    ${filterJoined}
    GROUP BY cg.id
    ORDER BY cg.num_datasets DESC, cg.human_symbol ASC
    LIMIT ?
  `);

  return { stmtHuman, stmtMouse, stmtSynonym };
}

// Keyword path: "control" returns every kind='control' entry, scoped by
// the current direction (perturbed vs target). Compiled once per
// direction, like the other prepared statements.
let stmtControlsAll: Database.Statement | null = null;
let stmtControlsPerturbed: Database.Statement | null = null;
let stmtControlsTarget: Database.Statement | null = null;

function prepareControlsStmt(
  db: Database.Database,
  directionalIdsTable: string | null,
): Database.Statement {
  const filterDirect = directionalIdsTable
    ? `AND id IN (SELECT central_gene_id FROM temp.${directionalIdsTable})`
    : "";
  return db.prepare(`
    SELECT id, human_symbol, mouse_symbols, human_synonyms, mouse_synonyms,
           num_datasets AS dataset_count, kind
    FROM central_gene
    WHERE kind = 'control'
    ${filterDirect}
    ORDER BY num_datasets DESC, human_symbol ASC, mouse_symbols ASC
    LIMIT ?
  `);
}

function getControlsStmt(
  db: Database.Database,
  direction: SearchDirection | null,
): Database.Statement | null {
  // Reuse the directional temp tables prepared by getStmts(); they're
  // keyed off the same db identity so the staleness check there suffices.
  if (direction == null) {
    if (!stmtControlsAll) stmtControlsAll = prepareControlsStmt(db, null);
    return stmtControlsAll;
  }
  if (direction === "perturbed") {
    if (!stmtControlsPerturbed) {
      const tempName = materializeDirectionalIds(db, "perturbed");
      if (!tempName) return null;
      stmtControlsPerturbed = prepareControlsStmt(db, tempName);
    }
    return stmtControlsPerturbed;
  }
  if (!stmtControlsTarget) {
    const tempName = materializeDirectionalIds(db, "target");
    if (!tempName) return null;
    stmtControlsTarget = prepareControlsStmt(db, tempName);
  }
  return stmtControlsTarget;
}

function getStmts(
  db: Database.Database,
  direction: SearchDirection | null,
): StmtTriple | null {
  if (stmtsDb !== db) {
    stmtsAll = null;
    stmtsPerturbed = null;
    stmtsTarget = null;
    stmtControlsAll = null;
    stmtControlsPerturbed = null;
    stmtControlsTarget = null;
    stmtsDb = db;
  }

  if (direction == null) {
    if (!stmtsAll) stmtsAll = prepareTriple(db, null);
    return stmtsAll;
  }

  if (direction === "perturbed") {
    if (!stmtsPerturbed) {
      const tempName = materializeDirectionalIds(db, "perturbed");
      // No link tables in this direction → no autocomplete results.
      if (!tempName) return null;
      stmtsPerturbed = prepareTriple(db, tempName);
    }
    return stmtsPerturbed;
  }

  if (!stmtsTarget) {
    const tempName = materializeDirectionalIds(db, "target");
    if (!tempName) return null;
    stmtsTarget = prepareTriple(db, tempName);
  }
  return stmtsTarget;
}

function rowToSuggestion(
  r: GeneSuggestionRow,
  searchText: string,
): SearchSuggestion {
  return {
    centralGeneId: r.id,
    searchQuery: searchText,
    humanSymbol: r.human_symbol,
    mouseSymbols: r.mouse_symbols
      ? r.mouse_symbols.split(",").filter(Boolean)
      : null,
    humanSynonyms: r.human_synonyms
      ? r.human_synonyms.split(",").filter(Boolean)
      : null,
    mouseSynonyms: r.mouse_synonyms
      ? r.mouse_synonyms.split(",").filter(Boolean)
      : null,
    datasetCount: r.dataset_count,
    kind: r.kind ?? "gene",
  };
}

export function fetchGeneSuggestions(
  text: string,
  pageLimit: number = 8,
  direction: SearchDirection | null = null,
): SearchSuggestion[] {
  const db = getDb();
  const searchText = text.trim().replace(/['"]/g, "");
  if (!searchText) return [];

  // Keyword path: "control" / "controls" → return every kind='control'
  // entry. Documented in docs/wrangler_gene_cleanup.md so users can
  // discover it. Bypasses the LIKE-prefix three-stage flow entirely.
  if (CONTROL_KEYWORDS.has(searchText.toLowerCase())) {
    // Ensure directional temp tables are materialized (getStmts has the
    // db-identity invalidation logic).
    getStmts(db, direction);
    const ctlStmt = getControlsStmt(db, direction);
    if (!ctlStmt) return [];
    const rows = ctlStmt.all(pageLimit) as GeneSuggestionRow[];
    return rows.map((r) => rowToSuggestion(r, searchText));
  }

  const likePrefix = `${searchText}%`;
  const stmts = getStmts(db, direction);
  if (!stmts) return [];
  const stages = [stmts.stmtHuman, stmts.stmtMouse, stmts.stmtSynonym];

  const seenIds = new Set<number>();
  const allRows: GeneSuggestionRow[] = [];

  for (const stmt of stages) {
    if (allRows.length >= pageLimit) break;

    const needed = pageLimit - allRows.length;
    // Fetch extra rows to account for dedup filtering
    const rows = stmt.all(likePrefix, needed + seenIds.size) as GeneSuggestionRow[];

    for (const row of rows) {
      if (seenIds.has(row.id)) continue;
      seenIds.add(row.id);
      allRows.push(row);
      if (allRows.length >= pageLimit) break;
    }
  }

  return allRows.map((r) => rowToSuggestion(r, searchText));
}
