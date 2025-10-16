import { getDb } from "@/lib/db";

export type SearchSuggestion = {
  centralGeneId: number;
  searchQuery: string;
  humanSymbol: string | null;
  mouseSymbols: string | null;
  humanSynonyms: string | null;
  mouseSynonyms: string | null;
  datasetCount: number;
};

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
  const seen = new Set<number>();

  const textStmt = db.prepare(
    `SELECT cg.id AS id,
            cg.human_symbol AS human_symbol,
            cg.mouse_symbols AS mouse_symbols,
            cg.human_synonyms AS human_synonyms,
            cg.mouse_synonyms AS mouse_synonyms
            cg.num_datasets AS dataset_count
     FROM central_gene cg
     LEFT JOIN synonyms s ON s.central_gene_id = cg.id
     WHERE (
      LOWER(cg.human_symbol) LIKE ?
      OR LOWER(cg.mouse_symbols) LIKE ?
      OR LOWER(s.synonym) LIKE ?
     )
     GROUP BY cg.id
     ORDER BY cg.num_datasets DESC, display_name ASC
     LIMIT ?`
  );

  const rows = textStmt.all(
    likePrefix,
    likePrefix,
    likePrefix,
    pageLimit * 2
  ) as Array<{
    id: number;
    human_symbol: string | null;
    mouse_symbols: string | null;
    human_synonyms: string | null;
    mouse_synonyms: string | null;
    dataset_count: number;
  }>;

  for (const r of rows) {
    if (seen.has(r.id)) continue;
    suggestions.push({
      centralGeneId: r.id,
      searchQuery: searchText,
      humanSymbol: r.human_symbol,
      mouseSymbols: r.mouse_symbols,
      humanSynonyms: r.human_synonyms,
      mouseSynonyms: r.mouse_synonyms,
      datasetCount: r.dataset_count,
    });
    if (suggestions.length >= pageLimit) break;
  }

  return suggestions;
}
