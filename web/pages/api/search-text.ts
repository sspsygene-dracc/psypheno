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

  const exactMatch = await getExactOrigSymbolMatch(searchText, pageLimit);

  // deduplicate suggestions -- but don't change order. Simply remove suggestions that have appeared higher
  const seen = new Set<string>();
  suggestions = suggestions.filter((suggestion) => {
    const key = suggestion.variant
      ? `${suggestion.hgncSymbol}:${suggestion.variant.pdot}:${suggestion.variant.cdot}:${suggestion.variant.rgene}`
      : suggestion.hgncSymbol;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });

  // Print query statistics after processing the request
  // printQueryStats();

  return res.status(200).json({ suggestions, sorryText, searchText: origText });
}
