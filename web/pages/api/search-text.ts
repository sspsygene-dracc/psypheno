import { fetchGeneSuggestions } from "@/lib/suggestions";
import { setReadCacheHeaders } from "@/lib/cache-headers";
import { SearchSuggestion } from "@/state/SearchSuggestion";
import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";

const querySchema = z.object({
  text: z.string(),
  direction: z.enum(["perturbed", "target"]).optional(),
});

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse,
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  // GET so the browser can cache repeat autocomplete queries (e.g. backspace
  // to a previously-typed prefix) without a network round trip. The body is
  // tiny — gene-symbol prefixes plus an optional direction.
  const parseResult = querySchema.safeParse({
    text: typeof req.query.text === "string" ? req.query.text : undefined,
    direction:
      typeof req.query.direction === "string" ? req.query.direction : undefined,
  });
  if (!parseResult.success) {
    return res.status(400).json({ error: "Invalid request query" });
  }

  const pageLimit = 8;
  const origText = parseResult.data.text;
  const searchText = parseResult.data.text.trim().replace(/['"]/g, "");

  if (!searchText) {
    setReadCacheHeaders(res);
    return res.status(200).json({ suggestions: [] });
  }

  try {
    const suggestions: SearchSuggestion[] = fetchGeneSuggestions(
      searchText,
      pageLimit,
      parseResult.data.direction ?? null,
    );
    setReadCacheHeaders(res);
    return res.status(200).json({ suggestions, searchText: origText });
  } catch (err) {
    console.error("Error querying search suggestions", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
