import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";

const ROW_LIMIT = 200;

const bodySchema = z.object({
  tableName: z.string().min(1),
  page: z.number().min(1),
  centralGeneId: z.number().min(0).optional(),
  perturbedCentralGeneId: z.number().nullable().optional(),
  targetCentralGeneId: z.number().nullable().optional(),
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

  const { tableName, page, centralGeneId, perturbedCentralGeneId, targetCentralGeneId } = parse.data;
  const isPairMode = centralGeneId === undefined;

  if (!isPairMode && centralGeneId === undefined) {
    return res.status(400).json({ error: "centralGeneId is required for general mode" });
  }
  if (isPairMode && !perturbedCentralGeneId && !targetCentralGeneId) {
    return res.status(400).json({ error: "At least one gene ID is required for pair mode" });
  }

  try {
    const db = getDb();

    const t = db
      .prepare(
        `SELECT table_name, display_columns, scalar_columns, link_tables FROM data_tables WHERE table_name = ?`
      )
      .get(tableName) as {
        table_name: string;
        display_columns: string;
        scalar_columns: string | null;
        link_tables: string | null;
      } | undefined;

    if (!t) {
      return res.status(400).json({ error: `Table not found: ${tableName}` });
    }

    const baseTable = sanitizeIdentifier(t.table_name);
    const displayCols = (t.display_columns || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map(sanitizeIdentifier);

    if (displayCols.length === 0) {
      return res.status(400).json({ error: "Table has no display columns" });
    }

    const selectCols = displayCols.map((c) => `b.${c}`).join(", ");
    const params: Array<string> = [];
    let fromAndWhere: string;

    if (!isPairMode) {
      // General mode: same logic as gene-data.ts
      const linkTables = (t.link_tables || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((entry) => {
          const parts = entry.split(":");
          const ltName = parts.length >= 2 ? parts[1] : parts[0];
          return sanitizeIdentifier(ltName);
        });

      if (linkTables.length === 0) {
        return res.status(400).json({ error: "Table has no link tables" });
      }

      const subqueries = linkTables.map((lt) => {
        params.push(String(centralGeneId));
        return `SELECT id FROM ${lt} WHERE central_gene_id = ?`;
      });
      const idSubquery = subqueries.length === 1
        ? subqueries[0]
        : subqueries.join(" UNION ");
      fromAndWhere = `FROM ${baseTable} b WHERE b.id IN (${idSubquery})`;
    } else {
      // Pair mode: same logic as gene-pair-data.ts
      const parsed = (t.link_tables || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((entry) => {
          const parts = entry.split(":");
          return {
            linkTable: sanitizeIdentifier(parts[1] ?? parts[0] ?? ""),
            isPerturbed: parts[2] === "1",
            isTarget: parts[3] === "1",
          };
        });

      const perturbedLTs = parsed.filter((p) => p.isPerturbed).map((p) => p.linkTable);
      const targetLTs = parsed.filter((p) => p.isTarget).map((p) => p.linkTable);

      if (perturbedLTs.length !== 1 || targetLTs.length !== 1) {
        return res.status(400).json({ error: "Table does not support pair mode" });
      }

      const subqueries: string[] = [];
      if (perturbedCentralGeneId) {
        subqueries.push(`SELECT id FROM ${perturbedLTs[0]} WHERE central_gene_id = ?`);
        params.push(String(perturbedCentralGeneId));
      }
      if (targetCentralGeneId) {
        subqueries.push(`SELECT id FROM ${targetLTs[0]} WHERE central_gene_id = ?`);
        params.push(String(targetCentralGeneId));
      }

      if (subqueries.length === 0) {
        return res.status(400).json({ error: "At least one gene ID required" });
      }

      const idSubquery = subqueries.length === 1
        ? subqueries[0]
        : subqueries.join(" INTERSECT ");
      fromAndWhere = `FROM ${baseTable} b WHERE b.id IN (${idSubquery})`;
    }

    // Count total rows
    const countSql = `SELECT COUNT(*) as cnt FROM (SELECT DISTINCT ${selectCols} ${fromAndWhere})`;
    const totalRows = (db.prepare(countSql).get(...params) as { cnt: number }).cnt;
    const totalPages = Math.max(1, Math.ceil(totalRows / ROW_LIMIT));

    // Clamp page
    const effectivePage = Math.min(page, totalPages);
    const offset = (effectivePage - 1) * ROW_LIMIT;

    // Fetch page
    const dataSql = `SELECT DISTINCT ${selectCols} ${fromAndWhere} LIMIT ${ROW_LIMIT} OFFSET ${offset}`;
    const rows = db.prepare(dataSql).all(...params) as Record<string, unknown>[];

    return res.status(200).json({
      tableName,
      rows,
      totalRows,
      page: effectivePage,
      totalPages,
    });
  } catch (err) {
    console.error("gene-table-page handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
