import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { performance } from "perf_hooks";
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
  const tHandler = performance.now();

  try {
    const db = getDb();
    const tables = db
      .prepare(
        `SELECT table_name, short_label, description, source, assay, field_labels, display_columns, scalar_columns, link_tables FROM data_tables ORDER BY id ASC`
      )
      .all() as Array<{
        table_name: string;
        short_label: string | null;
        description: string | null;
        source: string | null;
        assay: string | null;
        field_labels: string | null;
        display_columns: string;
        scalar_columns: string | null;
        link_tables: string | null;
      }>;

    const results: Array<{
      tableName: string;
      shortLabel: string | null;
      description: string | null;
      source: string | null;
      assay: string[];
      fieldLabels: Record<string, string> | null;
      displayColumns: string[];
      scalarColumns: string[];
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
        const tq = performance.now();
        const result = queryFirstPage(db, query.selectCols, query.fromAndWhere, query.params);
        const queryMs = performance.now() - tq;
        console.log(`[gene-pair-data] table=${baseTable} time=${queryMs.toFixed(1)}ms`);

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
          description: t.description ?? null,
          source: t.source ?? null,
          assay,
          fieldLabels,
          displayColumns: displayCols,
          scalarColumns: (t.scalar_columns || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          rows: result.rows,
          totalRows: result.totalRows,
        });
      } catch (innerErr) {
        // eslint-disable-next-line no-console
        console.error(`Pair query failed for table ${baseTable}`, innerErr);
      }
    }

    const totalMs = performance.now() - tHandler;
    console.log(`[gene-pair-data] TOTAL time=${totalMs.toFixed(1)}ms tables_with_results=${results.length}`);
    return res.status(200).json({ perturbedCentralGeneId, targetCentralGeneId, results });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("gene-pair-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
