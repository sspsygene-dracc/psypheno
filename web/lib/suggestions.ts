import { getDb } from "@/lib/db";
import { SearchSuggestion } from "@/state/SearchSuggestion";

interface GeneSuggestionRow {
  id: number;
  human_symbol: string | null;
  mouse_symbols: string | null;
  human_synonyms: string | null;
  mouse_synonyms: string | null;
  dataset_count: number;
}

export function fetchGeneSuggestions(
  text: string,
  pageLimit: number = 8
): SearchSuggestion[] {
  const db = getDb();
  const searchText = text.trim().replace(/['"]/g, "");
  if (!searchText) return [];

  const lower = searchText.toLowerCase();
  const likePrefix = `${lower}%`;

  // Collect suggestions, prioritizing numeric id match if provided
  const suggestions: SearchSuggestion[] = [];

  const whereClauses: string[] = [
    "LOWER(cg.human_symbol) LIKE ?",
    "LOWER(ms.symbol) LIKE ?",
    "LOWER(gs.synonym) LIKE ?",
  ];

  let whereClauseIdx = 0;

  const allRows: GeneSuggestionRow[] = [];
  while (allRows.length < pageLimit && whereClauseIdx < whereClauses.length) {
    const whereClause = whereClauses[whereClauseIdx];

    const seen = allRows.map((r) => r.id);
    const notInClause = seen.length
      ? `AND cg.id NOT IN (${seen.map(() => "?").join(",")})`
      : "";

    const sql = `SELECT DISTINCT cg.id AS id,
              cg.human_symbol AS human_symbol,
              cg.mouse_symbols AS mouse_symbols,
              cg.human_synonyms AS human_synonyms,
              cg.mouse_synonyms AS mouse_synonyms,
              cg.num_datasets AS dataset_count
      FROM central_gene cg
      LEFT JOIN extra_gene_synonyms gs ON gs.central_gene_id = cg.id
      LEFT JOIN extra_mouse_symbols ms ON ms.central_gene_id = cg.id
      WHERE ${whereClause}
      ${notInClause}
      GROUP BY cg.id
      ORDER BY cg.num_datasets DESC,
      cg.human_symbol ASC,
      cg.mouse_symbols ASC
      LIMIT ?`;

    const textStmt = db.prepare(sql);
    const params = seen.length
      ? [likePrefix, ...seen, pageLimit]
      : [likePrefix, pageLimit];
    const rows = textStmt.all(...params) as Array<GeneSuggestionRow>;

    allRows.push(...rows.slice(0, pageLimit - allRows.length));
    whereClauseIdx++;
  }

  for (const r of allRows) {
    const humanSynonyms = r.human_synonyms
      ? r.human_synonyms.split(",").filter(Boolean)
      : null;
    const mouseSynonyms = r.mouse_synonyms
      ? r.mouse_synonyms.split(",").filter(Boolean)
      : null;
    const mouseSymbols = r.mouse_symbols
      ? r.mouse_symbols.split(",").filter(Boolean)
      : null;
    suggestions.push({
      centralGeneId: r.id,
      searchQuery: searchText,
      humanSymbol: r.human_symbol,
      mouseSymbols: mouseSymbols,
      humanSynonyms: humanSynonyms,
      mouseSynonyms: mouseSynonyms,
      datasetCount: r.dataset_count,
    });
    if (suggestions.length >= pageLimit) break;
  }

  return suggestions;
}
