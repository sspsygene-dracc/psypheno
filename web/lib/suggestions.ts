import { getDb } from "@/lib/db";
import { SearchSuggestion } from "@/state/SearchSuggestion";
import type Database from "better-sqlite3";

interface GeneSuggestionRow {
  id: number;
  human_symbol: string | null;
  mouse_symbols: string | null;
  human_synonyms: string | null;
  mouse_synonyms: string | null;
  dataset_count: number;
}

// Pre-prepared statements, cached on first use
let stmtsDb: Database.Database | null = null;
let stmtHuman: Database.Statement | null = null;
let stmtMouse: Database.Statement | null = null;
let stmtSynonym: Database.Statement | null = null;

function getStmts(db: Database.Database) {
  if (stmtsDb === db && stmtHuman && stmtMouse && stmtSynonym) {
    return { stmtHuman, stmtMouse, stmtSynonym };
  }

  // Stage 1: human symbol — no JOINs needed, query central_gene directly
  stmtHuman = db.prepare(`
    SELECT id, human_symbol, mouse_symbols, human_synonyms, mouse_synonyms,
           num_datasets AS dataset_count
    FROM central_gene
    WHERE human_symbol LIKE ? COLLATE NOCASE
    ORDER BY num_datasets DESC, human_symbol ASC
    LIMIT ?
  `);

  // Stage 2: mouse symbol — start from extra_mouse_symbols, join to central_gene
  stmtMouse = db.prepare(`
    SELECT cg.id AS id, cg.human_symbol AS human_symbol,
           cg.mouse_symbols AS mouse_symbols, cg.human_synonyms AS human_synonyms,
           cg.mouse_synonyms AS mouse_synonyms, cg.num_datasets AS dataset_count
    FROM extra_mouse_symbols ms
    JOIN central_gene cg ON cg.id = ms.central_gene_id
    WHERE ms.symbol LIKE ? COLLATE NOCASE
    GROUP BY cg.id
    ORDER BY cg.num_datasets DESC, cg.human_symbol ASC
    LIMIT ?
  `);

  // Stage 3: synonym — start from extra_gene_synonyms, join to central_gene
  stmtSynonym = db.prepare(`
    SELECT cg.id AS id, cg.human_symbol AS human_symbol,
           cg.mouse_symbols AS mouse_symbols, cg.human_synonyms AS human_synonyms,
           cg.mouse_synonyms AS mouse_synonyms, cg.num_datasets AS dataset_count
    FROM extra_gene_synonyms gs
    JOIN central_gene cg ON cg.id = gs.central_gene_id
    WHERE gs.synonym LIKE ? COLLATE NOCASE
    GROUP BY cg.id
    ORDER BY cg.num_datasets DESC, cg.human_symbol ASC
    LIMIT ?
  `);

  stmtsDb = db;
  return { stmtHuman, stmtMouse, stmtSynonym };
}

export function fetchGeneSuggestions(
  text: string,
  pageLimit: number = 8
): SearchSuggestion[] {
  const db = getDb();
  const searchText = text.trim().replace(/['"]/g, "");
  if (!searchText) return [];

  const likePrefix = `${searchText}%`;
  const stmts = getStmts(db);
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

  return allRows.map((r) => ({
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
  }));
}
