import { fetchGeneSuggestions } from "@/lib/suggestions";
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

  try {
    const suggestions: SearchSuggestion[] = fetchGeneSuggestions(searchText, pageLimit);
    return res.status(200).json({ suggestions, searchText: origText });
  } catch (err) {
    console.error("Error querying search suggestions", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
