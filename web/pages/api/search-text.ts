import { getDb } from "@/lib/db";

import { SearchSuggestion } from "@/state/SearchSuggestion";
import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";

const querySchema = z.object({
  text: z.string(),
});

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const parseResult = querySchema.safeParse(req.body);
  if (!parseResult.success) {
    console.error("Invalid request body", parseResult.error);
    return res.status(400).json({ error: "Invalid request body" });
  }

  const pageLimit = 8;
  const origText = parseResult.data.text;
  const searchText = parseResult.data.text.trim().replace(/['"]/g, "");

  if (!searchText) {
    return res.status(200).json({ suggestions: [] });
  }

  let suggestions: SearchSuggestion[] = [];

  try {
    const db = getDb();

    const likeParam = `%${searchText}%`;
    const isNumeric = /^\d+$/.test(searchText);

    // Helper to run a search against one species table
    const runSpeciesQuery = (
      tableName: string,
      species: "human" | "mouse" | "zebrafish"
    ): SearchSuggestion[] => {
      // Prefer official symbols first (is_symbol = 1), then name ASC
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

    // Merge and deduplicate by species + entrezId
    const seen = new Set<string>();
    for (const s of [...human, ...mouse, ...zebrafish]) {
      const key = s.entrezId;
      if (!seen.has(key)) {
        seen.add(key);
        suggestions.push(s);
        if (suggestions.length >= pageLimit) break;
      }
    }
  } catch (err) {
    console.error("Error querying search suggestions", err);
    return res.status(500).json({ error: "Internal server error" });
  }

  return res.status(200).json({ suggestions, searchText: origText });
}
