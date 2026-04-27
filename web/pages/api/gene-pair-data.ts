import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { sanitizeIdentifier, parseDisplayColumns, buildGeneQuery, queryFirstPage } from "@/lib/gene-query";

const bodySchema = z.object({
  perturbedCentralGeneId: z.number().nullable(),
  targetCentralGeneId: z.number().nullable(),
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

  const { perturbedCentralGeneId, targetCentralGeneId } = parse.data;

  try {
    const db = getDb();
    const tables = db
      .prepare(
        `SELECT table_name, short_label, medium_label, long_label, description, source, assay, field_labels, display_columns, scalar_columns, link_tables, pvalue_column, fdr_column FROM data_tables ORDER BY id ASC`
      )
      .all() as Array<{
        table_name: string;
        short_label: string | null;
        medium_label: string | null;
        long_label: string | null;
        description: string | null;
        source: string | null;
        assay: string | null;
        field_labels: string | null;
        display_columns: string;
        scalar_columns: string | null;
        link_tables: string | null;
        pvalue_column: string | null;
        fdr_column: string | null;
      }>;

    const results: Array<{
      tableName: string;
      shortLabel: string | null;
      mediumLabel: string | null;
      longLabel: string | null;
      description: string | null;
      source: string | null;
      assay: string[];
      fieldLabels: Record<string, string> | null;
      displayColumns: string[];
      scalarColumns: string[];
      pvalueColumn: string | null;
      fdrColumn: string | null;
      rows: Record<string, unknown>[];
      totalRows: number;
    }> = [];

    for (const t of tables) {
      const baseTable = sanitizeIdentifier(t.table_name);
      const displayCols = parseDisplayColumns(t.display_columns);
      if (displayCols.length === 0) continue;

      const query = buildGeneQuery({
        baseTable,
        displayCols,
        linkTablesRaw: t.link_tables || "",
        perturbedCentralGeneId,
        targetCentralGeneId,
      });
      if (!query) continue;

      try {
        const result = queryFirstPage(db, query.selectCols, query.fromAndWhere, query.params);
        if (!result) continue;

        let fieldLabels: Record<string, string> | null = null;
        if (t.field_labels) {
          try {
            fieldLabels = JSON.parse(t.field_labels);
          } catch {
            fieldLabels = null;
          }
        }
        const assay = (t.assay || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
        results.push({
          tableName: t.table_name,
          shortLabel: t.short_label ?? null,
          mediumLabel: t.medium_label ?? null,
          longLabel: t.long_label ?? null,
          description: t.description ?? null,
          source: t.source ?? null,
          assay,
          fieldLabels,
          displayColumns: displayCols,
          scalarColumns: (t.scalar_columns || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          pvalueColumn: t.pvalue_column ?? null,
          fdrColumn: t.fdr_column ?? null,
          rows: result.rows,
          totalRows: result.totalRows,
        });
      } catch (innerErr) {
        // eslint-disable-next-line no-console
        console.error(`Pair query failed for table ${baseTable}`, innerErr);
      }
    }

    return res.status(200).json({ perturbedCentralGeneId, targetCentralGeneId, results });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("gene-pair-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
