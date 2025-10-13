import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";

const bodySchema = z.object({
  entrezId: z.string().min(1),
  perturbedEntrezId: z.string().optional(),
  targetEntrezId: z.string().optional(),
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
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const parse = bodySchema.safeParse(req.body);
  if (!parse.success) {
    return res.status(400).json({ error: "Invalid request body" });
  }

  const entrezId = parse.data.entrezId;
  const perturbedEntrezId = parse.data.perturbedEntrezId || null;
  const targetEntrezId = parse.data.targetEntrezId || null;

  try {
    const db = getDb();

    const tables = db
      .prepare(
        `SELECT table_name, gene_columns, display_columns, link_tables FROM data_tables ORDER BY id ASC`
      )
      .all() as Array<{
      table_name: string;
      gene_columns: string;
      display_columns: string;
      link_tables: string | null;
    }>;

    const results: Array<{
      tableName: string;
      displayColumns: string[];
      rows: Record<string, unknown>[];
    }> = [];

    for (const t of tables) {
      const baseTable = sanitizeIdentifier(t.table_name);
      const displayCols = (t.display_columns || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map(sanitizeIdentifier);

      if (displayCols.length === 0) continue;

      // Parse link tables list with entries like "gene_col:table_name:is_perturbed:is_target"
      // Keep flags so we can filter by roles when provided
      const parsedLinkTables = (t.link_tables || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((entry) => {
          const parts = entry.split(":");
          const tableName = parts.length >= 2 ? parts[1] : parts[0];
          return {
            tableName: sanitizeIdentifier(tableName),
            isPerturbed: parts[2] === "1",
            isTarget: parts[3] === "1",
          };
        });

      // Build SQL
      const selectCols = displayCols.map((c) => `b.${c}`).join(", ");

      let sql = `SELECT ${selectCols} FROM ${baseTable} b`;
      const params: Array<string> = [];

      if (parsedLinkTables.length === 0) {
        // No way to filter for this table
        continue;
      }

      const whereOrGeneral: string[] = [];
      const whereOrPerturbed: string[] = [];
      const whereOrTarget: string[] = [];
      parsedLinkTables.forEach((lt, idx) => {
        const alias = `lt${idx}`;
        sql += ` LEFT JOIN ${lt.tableName} ${alias} ON b.id = ${alias}.id`;
        whereOrGeneral.push(`${alias}.entrez_gene = ?`);
        if (lt.isPerturbed) whereOrPerturbed.push(`${alias}.entrez_gene = ?`);
        if (lt.isTarget) whereOrTarget.push(`${alias}.entrez_gene = ?`);
      });

      const whereAndParts: string[] = [];
      if (whereOrGeneral.length > 0) {
        whereAndParts.push(`(${whereOrGeneral.join(" OR ")})`);
        params.push(String(entrezId));
      }
      if (perturbedEntrezId && whereOrPerturbed.length > 0) {
        whereAndParts.push(`(${whereOrPerturbed.join(" OR ")})`);
        params.push(String(perturbedEntrezId));
      }
      if (targetEntrezId && whereOrTarget.length > 0) {
        whereAndParts.push(`(${whereOrTarget.join(" OR ")})`);
        params.push(String(targetEntrezId));
      }

      if (whereAndParts.length === 0) continue;
      sql += ` WHERE ${whereAndParts.join(" AND ")} LIMIT 100`;

      try {
        const stmt = db.prepare(sql);
        const rows = stmt.all(...params) as Record<string, unknown>[];
        if (rows.length > 0) {
          results.push({
            tableName: t.table_name,
            displayColumns: displayCols,
            rows,
          });
        }
      } catch (innerErr) {
        // Skip tables that fail (e.g., column missing) to keep response robust
        // eslint-disable-next-line no-console
        console.error(`Query failed for table ${baseTable}`, innerErr);
      }
    }

    return res.status(200).json({ entrezId, results });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("gene-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
