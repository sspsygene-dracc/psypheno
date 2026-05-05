import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { fetchGeneSuggestions } from "@/lib/suggestions";
import {
  ALL_CONTROLS_SENTINEL_ID,
  parseLinkTablesForDirection,
  sanitizeIdentifier,
  type SearchDirection,
} from "@/lib/gene-query";

const bodySchema = z.object({
  perturbedSymbol: z.string().nullable(),
  targetSymbol: z.string().nullable(),
});

// Resolve a user-entered symbol to a central_gene_id, mirroring
// resolveSymbol() on the home page (index.tsx). Returns
// ALL_CONTROLS_SENTINEL_ID for the CONTROL pseudo-symbol so callers can
// expand it through the same kind='control' subquery used elsewhere.
function resolveSymbolToId(
  symbol: string,
  direction: SearchDirection,
): number | null {
  if (symbol.toUpperCase() === "CONTROL") {
    return ALL_CONTROLS_SENTINEL_ID;
  }
  const suggestions = fetchGeneSuggestions(symbol, 8, direction);
  const exact = suggestions.find((s) => s.humanSymbol === symbol);
  const pick = exact ?? suggestions[0] ?? null;
  return pick?.centralGeneId ?? null;
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse,
) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const parsed = bodySchema.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ error: "Invalid request body" });
  }

  const { perturbedSymbol, targetSymbol } = parsed.data;
  if (!perturbedSymbol || !targetSymbol) {
    return res.status(200).json({ exists: false });
  }

  try {
    const perturbedId = resolveSymbolToId(perturbedSymbol, "perturbed");
    const targetId = resolveSymbolToId(targetSymbol, "target");
    if (perturbedId == null || targetId == null) {
      return res.status(200).json({ exists: false });
    }

    const db = getDb();
    const tables = db
      .prepare(`SELECT link_tables FROM data_tables`)
      .all() as Array<{ link_tables: string | null }>;

    const allControls = `SELECT id FROM central_gene WHERE kind = 'control'`;
    const [pertCond, pertParams]: [string, number[]] =
      perturbedId === ALL_CONTROLS_SENTINEL_ID
        ? [`IN (${allControls})`, []]
        : [`= ?`, [perturbedId]];
    const [targCond, targParams]: [string, number[]] =
      targetId === ALL_CONTROLS_SENTINEL_ID
        ? [`IN (${allControls})`, []]
        : [`= ?`, [targetId]];

    for (const t of tables) {
      const raw = t.link_tables || "";
      const pertLT = parseLinkTablesForDirection(raw, "perturbed");
      const targLT = parseLinkTablesForDirection(raw, "target");
      if (pertLT.length !== 1 || targLT.length !== 1) continue;
      const p = sanitizeIdentifier(pertLT[0]);
      const tgt = sanitizeIdentifier(targLT[0]);

      const sql = `
        SELECT 1
        FROM ${p} p
        JOIN ${tgt} t ON t.id = p.id
        WHERE p.central_gene_id ${pertCond}
          AND t.central_gene_id ${targCond}
        LIMIT 1`;
      const hit = db.prepare(sql).get(...pertParams, ...targParams);
      if (hit) {
        return res.status(200).json({ exists: true });
      }
    }

    return res.status(200).json({ exists: false });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("gene-pair-exists handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
