import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";

const querySchema = z.object({
  tableName: z.string().min(1),
});

function sanitizeIdentifier(id: string): string {
  // Allow only alphanumeric and underscore to avoid SQL injection via identifiers
  if (!/^\w+$/.test(id)) throw new Error(`Invalid identifier: ${id}`);
  return id;
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const parse = querySchema.safeParse(req.query);
  if (!parse.success) {
    return res.status(400).json({ error: "Invalid request query" });
  }

  const tableName = sanitizeIdentifier(parse.data.tableName);

  try {
    const db = getDb();

    // Get table metadata
    const metadata = db
      .prepare(
        `SELECT display_columns FROM data_tables WHERE table_name = ?`
      )
      .get(tableName) as { display_columns: string } | undefined;

    if (!metadata) {
      return res.status(404).json({ error: "Dataset not found" });
    }

    const displayCols = metadata.display_columns
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map(sanitizeIdentifier);

    if (displayCols.length === 0) {
      return res.status(400).json({ error: "No display columns found" });
    }

    // Get all data from the table
    const selectCols = displayCols.join(", ");
    const sql = `SELECT ${selectCols} FROM ${tableName} LIMIT 101`;

    const rows = db.prepare(sql).all() as Record<string, unknown>[];

    return res.status(200).json({
      tableName,
      displayColumns: displayCols,
      rows,
    });
  } catch (err) {
    console.error("dataset-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}

