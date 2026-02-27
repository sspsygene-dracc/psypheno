import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { sanitizeIdentifier, parseDisplayColumns, parseNonPerturbedLinkTables } from "@/lib/gene-query";

const bodySchema = z.object({
  centralGeneId: z.number().min(0),
  filterBy: z.enum(["pvalue", "fdr"]),
  sortBy: z.enum(["pvalue", "fdr"]),
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

  const { centralGeneId, filterBy, sortBy } = parse.data;

  try {
    const db = getDb();

    // Fetch all tables that have the relevant pvalue/fdr columns
    const allTables = db
      .prepare(
        `SELECT table_name, short_label, pvalue_column, fdr_column,
                link_tables, field_labels, display_columns, scalar_columns
         FROM data_tables
         WHERE pvalue_column IS NOT NULL OR fdr_column IS NOT NULL
         ORDER BY id ASC`
      )
      .all() as Array<{
        table_name: string;
        short_label: string | null;
        pvalue_column: string | null;
        fdr_column: string | null;
        link_tables: string | null;
        field_labels: string | null;
        display_columns: string;
        scalar_columns: string | null;
      }>;

    const results: Array<{
      tableName: string;
      shortLabel: string | null;
      pvalueColumn: string | null;
      fdrColumn: string | null;
      fieldLabels: Record<string, string> | null;
      displayColumns: string[];
      scalarColumns: string[];
      rows: Record<string, unknown>[];
      totalSignificantRows: number;
    }> = [];

    for (const t of allTables) {
      // Determine which column to filter on
      const filterCol =
        filterBy === "pvalue" ? t.pvalue_column : t.fdr_column;
      if (!filterCol) continue; // Table doesn't have the requested column

      // Determine which column to sort by (fall back to filter column)
      const sortCol =
        sortBy === "pvalue"
          ? t.pvalue_column || t.fdr_column
          : t.fdr_column || t.pvalue_column;
      if (!sortCol) continue;

      const baseTable = sanitizeIdentifier(t.table_name);
      const safeFilterCol = sanitizeIdentifier(filterCol);
      const safeSortCol = sanitizeIdentifier(sortCol);
      const displayCols = parseDisplayColumns(t.display_columns);
      if (displayCols.length === 0) continue;

      // Build link table subquery (skip perturbed link tables)
      const linkTableNames = parseNonPerturbedLinkTables(t.link_tables || "");
      if (linkTableNames.length === 0) continue;

      const subqueries = linkTableNames.map((lt) => {
        return `SELECT id FROM ${lt} WHERE central_gene_id = ?`;
      });
      const idSubquery =
        subqueries.length === 1 ? subqueries[0] : subqueries.join(" UNION ");
      const params = linkTableNames.map(() => String(centralGeneId));

      const selectCols = displayCols.map((c) => `b.${c}`).join(", ");

      try {
        const query = `SELECT DISTINCT ${selectCols} FROM ${baseTable} b
          WHERE b.id IN (${idSubquery})
          AND b.${safeFilterCol} IS NOT NULL
          AND b.${safeFilterCol} < 0.05
          ORDER BY b.${safeSortCol} ASC
          LIMIT 500`;

        const rows = db.prepare(query).all(...params) as Record<
          string,
          unknown
        >[];

        if (rows.length === 0) continue;

        // Count total significant rows
        const countQuery = `SELECT COUNT(*) as cnt FROM (
          SELECT DISTINCT ${selectCols} FROM ${baseTable} b
          WHERE b.id IN (${idSubquery})
          AND b.${safeFilterCol} IS NOT NULL
          AND b.${safeFilterCol} < 0.05
        )`;
        const countResult = db.prepare(countQuery).get(...params) as {
          cnt: number;
        };

        let fieldLabels: Record<string, string> | null = null;
        if (t.field_labels) {
          try {
            fieldLabels = JSON.parse(t.field_labels);
          } catch {
            fieldLabels = null;
          }
        }

        results.push({
          tableName: t.table_name,
          shortLabel: t.short_label,
          pvalueColumn: t.pvalue_column,
          fdrColumn: t.fdr_column,
          fieldLabels,
          displayColumns: displayCols,
          scalarColumns: (t.scalar_columns || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          rows,
          totalSignificantRows: countResult.cnt,
        });
      } catch (innerErr) {
        console.error(`Query failed for table ${baseTable}`, innerErr);
      }
    }

    return res.status(200).json({ centralGeneId, tables: results });
  } catch (err) {
    console.error("significant-rows handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
