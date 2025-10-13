import { getDb } from "@/lib/db";

export type SearchSuggestion = {
  species: string;
  name: string;
  entrezId: string;
};

export function fetchGeneSuggestions(text: string, pageLimit: number = 8): SearchSuggestion[] {
  const db = getDb();
  const searchText = text.trim().replace(/['"]/g, "");
  if (!searchText) return [];

  const likeParam = `${searchText}%`;
  const isNumeric = /^\d+$/.test(searchText);

  const runSpeciesQuery = (
    tableName: string,
    species: "human" | "mouse" | "zebrafish"
  ): SearchSuggestion[] => {
    const baseWhere = "name LIKE ?";
    const idWhere = isNumeric ? " OR entrez_id = ?" : "";
    const sql = `SELECT name, entrez_id FROM ${tableName} WHERE ${baseWhere}${idWhere} ORDER BY is_symbol DESC, name ASC LIMIT ?`;

    const stmt = db.prepare(sql);
    const rows = isNumeric
      ? stmt.all(likeParam, Number(searchText), pageLimit)
      : stmt.all(likeParam, pageLimit);

    return rows.map((r: any) => ({
      species,
      name: String(r.name),
      entrezId: String(r.entrez_id),
    }));
  };

  const human = runSpeciesQuery("human_entrez_gene", "human");
  const mouse = runSpeciesQuery("mouse_entrez_gene", "mouse");
  const zebrafish = runSpeciesQuery("zebrafish_entrez_gene", "zebrafish");

  const suggestions: SearchSuggestion[] = [];
  const seen = new Set<string>();
  for (const s of [...human, ...mouse, ...zebrafish]) {
    const key = s.entrezId;
    if (!seen.has(key)) {
      seen.add(key);
      suggestions.push(s);
      if (suggestions.length >= pageLimit) break;
    }
  }
  return suggestions;
}


