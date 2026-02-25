import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { sanitizeIdentifier, parseDisplayColumns, buildGeneQuery, queryPage } from "@/lib/gene-query";

const bodySchema = z.object({
  tableName: z.string().min(1),
  page: z.number().min(1),
  centralGeneId: z.number().min(0).optional(),
  perturbedCentralGeneId: z.number().nullable().optional(),
  targetCentralGeneId: z.number().nullable().optional(),
});

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const parse = bodySchema.safeParse(req.body);
  if (!parse.success) {
    return res.status(400).json({ error: "Invalid request body" });
  }

  const { tableName, page, centralGeneId, perturbedCentralGeneId, targetCentralGeneId } = parse.data;
  const isPairMode = centralGeneId === undefined;

  if (isPairMode && !perturbedCentralGeneId && !targetCentralGeneId) {
    return res.status(400).json({ error: "At least one gene ID is required" });
  }

  try {
    const db = getDb();

    const t = db
      .prepare(
        `SELECT table_name, display_columns, link_tables FROM data_tables WHERE table_name = ?`
      )
      .get(tableName) as {
        table_name: string;
        display_columns: string;
        link_tables: string | null;
      } | undefined;

    if (!t) {
      return res.status(400).json({ error: `Table not found: ${tableName}` });
    }

    const baseTable = sanitizeIdentifier(t.table_name);
    const displayCols = parseDisplayColumns(t.display_columns);

    if (displayCols.length === 0) {
      return res.status(400).json({ error: "Table has no display columns" });
    }

    const query = isPairMode
      ? buildGeneQuery({ baseTable, displayCols, linkTablesRaw: t.link_tables || "", perturbedCentralGeneId, targetCentralGeneId })
      : buildGeneQuery({ baseTable, displayCols, linkTablesRaw: t.link_tables || "", centralGeneId });

    if (!query) {
      return res.status(400).json({ error: "Cannot query this table with the given parameters" });
    }

    const result = queryPage(db, query.selectCols, query.fromAndWhere, query.params, page);

    return res.status(200).json({ tableName, ...result });
  } catch (err) {
    console.error("gene-table-page handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
