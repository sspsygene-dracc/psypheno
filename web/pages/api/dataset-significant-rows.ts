import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { sanitizeIdentifier, parseDisplayColumns } from "@/lib/gene-query";

const bodySchema = z.object({
  tableName: z.string(),
  page: z.number().int().min(1).default(1),
  pageSize: z.number().int().min(1).max(100).default(25),
  filterBy: z.enum(["pvalue", "fdr"]),
  sortBy: z.enum(["pvalue", "fdr"]),
  sortDir: z.enum(["asc", "desc"]).default("asc"),
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

  const { tableName, page, pageSize, filterBy, sortBy, sortDir } = parse.data;

  try {
    const db = getDb();

    // Fetch table metadata
    const tableMeta = db
      .prepare(
        `SELECT table_name, short_label, pvalue_column, fdr_column,
                field_labels, display_columns, scalar_columns
         FROM data_tables
         WHERE table_name = ?
         AND (pvalue_column IS NOT NULL OR fdr_column IS NOT NULL)`
      )
      .get(tableName) as {
        table_name: string;
        short_label: string | null;
        pvalue_column: string | null;
        fdr_column: string | null;
        field_labels: string | null;
        display_columns: string;
        scalar_columns: string | null;
      } | undefined;

    if (!tableMeta) {
      return res.status(404).json({ error: "Table not found" });
    }

    const filterCol =
      filterBy === "pvalue" ? tableMeta.pvalue_column : tableMeta.fdr_column;
    if (!filterCol) {
      return res.status(400).json({ error: `Table has no ${filterBy} column` });
    }

    const sortCol =
      sortBy === "pvalue"
        ? tableMeta.pvalue_column || tableMeta.fdr_column
        : tableMeta.fdr_column || tableMeta.pvalue_column;
    if (!sortCol) {
      return res.status(400).json({ error: "No sortable column" });
    }

    const baseTable = sanitizeIdentifier(tableMeta.table_name);
    const safeFilterCol = sanitizeIdentifier(filterCol);
    const safeSortCol = sanitizeIdentifier(sortCol);
    const displayCols = parseDisplayColumns(tableMeta.display_columns);
    if (displayCols.length === 0) {
      return res.status(400).json({ error: "No display columns" });
    }

    const selectCols = displayCols.map((c) => sanitizeIdentifier(c)).join(", ");
    const offset = (page - 1) * pageSize;

    const rows = db
      .prepare(
        `SELECT ${selectCols} FROM ${baseTable}
         WHERE ${safeFilterCol} IS NOT NULL
         AND ${safeFilterCol} < 0.05
         ORDER BY ${safeSortCol} ${sortDir === "desc" ? "DESC" : "ASC"} ${sortDir === "asc" ? "NULLS LAST" : "NULLS FIRST"}
         LIMIT ? OFFSET ?`
      )
      .all(pageSize, offset) as Record<string, unknown>[];

    const countResult = db
      .prepare(
        `SELECT COUNT(*) as cnt FROM ${baseTable}
         WHERE ${safeFilterCol} IS NOT NULL
         AND ${safeFilterCol} < 0.05`
      )
      .get() as { cnt: number };

    let fieldLabels: Record<string, string> | null = null;
    if (tableMeta.field_labels) {
      try {
        fieldLabels = JSON.parse(tableMeta.field_labels);
      } catch {
        fieldLabels = null;
      }
    }

    return res.status(200).json({
      tableName: tableMeta.table_name,
      shortLabel: tableMeta.short_label,
      pvalueColumn: tableMeta.pvalue_column,
      fdrColumn: tableMeta.fdr_column,
      fieldLabels,
      displayColumns: displayCols,
      scalarColumns: (tableMeta.scalar_columns || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      rows,
      totalRows: countResult.cnt,
      page,
      pageSize,
    });
  } catch (err) {
    console.error("dataset-significant-rows handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
