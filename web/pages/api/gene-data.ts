import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";

const bodySchema = z.object({
  entrezId: z.string().min(1),
});

function sanitizeIdentifier(id: string): string {
  // Allow only alphanumeric and underscore to avoid SQL injection via identifiers
  if (!/^\w+$/.test(id)) throw new Error(`Invalid identifier: ${id}`);
  return id;
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const parse = bodySchema.safeParse(req.body);
  if (!parse.success) {
    return res.status(400).json({ error: "Invalid request body" });
  }

  const entrezId = parse.data.entrezId;

  try {
    const db = getDb();

    const tables = db
      .prepare(
        `SELECT table_name, gene_columns, display_columns FROM data_tables ORDER BY id ASC`
      )
      .all() as Array<{ table_name: string; gene_columns: string; display_columns: string }>;

    const results: Array<{
      tableName: string;
      displayColumns: string[];
      rows: Record<string, unknown>[];
    }> = [];

    for (const t of tables) {
      const tableName = sanitizeIdentifier(t.table_name);
      const geneCols = (t.gene_columns || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map(sanitizeIdentifier);
      const displayCols = (t.display_columns || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map(sanitizeIdentifier);

      if (geneCols.length === 0 || displayCols.length === 0) continue;

      const where = geneCols.map((c) => `${c} = ?`).join(" OR ");
      const selectCols = displayCols.join(", ");
      const sql = `SELECT ${selectCols} FROM ${tableName} WHERE ${where} LIMIT 100`;

      try {
        const stmt = db.prepare(sql);
        const params = Array(geneCols.length).fill(Number(entrezId));
        const rows = stmt.all(...params) as Record<string, unknown>[];
        if (rows.length > 0) {
          results.push({ tableName: t.table_name, displayColumns: displayCols, rows });
        }
      } catch (innerErr) {
        // Skip tables that fail (e.g., column missing) to keep response robust
        // eslint-disable-next-line no-console
        console.error(`Query failed for table ${tableName}`, innerErr);
      }
    }

    return res.status(200).json({ entrezId, results });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("gene-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}


