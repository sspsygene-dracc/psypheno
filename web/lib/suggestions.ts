import { getDb } from "@/lib/db";

export type SearchSuggestion = {
  species: string;
  name: string;
  entrezId: string;
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

  const toSpecies = (
    humanSymbol: string | null,
    mouseSymbols: string | null
  ): string => {
    const hasHuman = !!(humanSymbol && humanSymbol.length > 0);
    const hasMouse = !!(mouseSymbols && mouseSymbols.length > 0);
    if (hasHuman && hasMouse) return "human/mouse";
    if (hasHuman) return "human";
    if (hasMouse) return "mouse";
    return "unknown";
  };

  // Collect suggestions, prioritizing numeric id match if provided
  const suggestions: SearchSuggestion[] = [];
  const seen = new Set<number>();

  const textStmt = db.prepare(
    `SELECT cg.id AS id,
            cg.human_symbol AS human_symbol,
            cg.mouse_symbols AS mouse_symbols,
            COALESCE(cg.human_symbol, cg.mouse_symbols, s.synonym, CAST(cg.id AS TEXT)) AS display_name
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
    display_name: string;
  }>;

  for (const r of rows) {
    if (seen.has(r.id)) continue;
    suggestions.push({
      species: toSpecies(r.human_symbol, r.mouse_symbols),
      name: r.display_name,
      entrezId: String(r.id),
    });
    if (suggestions.length >= pageLimit) break;
  }

  return suggestions;
}
