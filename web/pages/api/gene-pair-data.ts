import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";

const bodySchema = z.object({
  perturbedEntrezId: z.string().nullable(),
  targetEntrezId: z.string().nullable(),
});

function sanitizeIdentifier(id: string): string {
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

  const { perturbedEntrezId, targetEntrezId } = parse.data;

  try {
    const db = getDb();
    const tables = db
      .prepare(
        `SELECT table_name, display_columns, link_tables FROM data_tables ORDER BY id ASC`
      )
      .all() as Array<{
      table_name: string;
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

      // Parse link tables with new 4-field format
      const parsed = (t.link_tables || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((entry) => {
          const parts = entry.split(":");
          return {
            geneColumn: parts[0] ?? null,
            linkTable: sanitizeIdentifier(parts[1] ?? parts[0] ?? ""),
            isPerturbed: parts[2] === "1",
            isTarget: parts[3] === "1",
          };
        });

      const perturbedLTs = parsed
        .filter((p) => p.isPerturbed)
        .map((p) => p.linkTable);
      const targetLTs = parsed
        .filter((p) => p.isTarget)
        .map((p) => p.linkTable);
      if (perturbedLTs.length != 1 || targetLTs.length != 1) continue;
      const perturbedLT = perturbedLTs[0];
      const targetLT = targetLTs[0];

      const selectCols = displayCols.map((c) => `b.${c}`).join(", ");
      let sql = `SELECT ${selectCols} FROM ${baseTable} b`;
      const params: Array<string> = [];

      // Join at least one perturbed and one target link table and require both ids
      const whereParts: string[] = [];
      if (perturbedEntrezId) {
        const lt = perturbedLT;
        sql += ` LEFT JOIN ${lt} p ON b.id = p.id`;
        whereParts.push(`p.central_gene_id = ?`);
        params.push(String(perturbedEntrezId));
      }
      if (targetEntrezId) {
        const lt = targetLT;
        sql += ` LEFT JOIN ${lt} t ON b.id = t.id`;
        whereParts.push(`t.central_gene_id = ?`);
        params.push(String(targetEntrezId));
      }

      sql += ` WHERE ${whereParts.join(" AND ")}`;

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
        // eslint-disable-next-line no-console
        console.error(`Pair query failed for table ${baseTable}`, innerErr);
      }
    }

    return res.status(200).json({ perturbedEntrezId, targetEntrezId, results });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("gene-pair-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
