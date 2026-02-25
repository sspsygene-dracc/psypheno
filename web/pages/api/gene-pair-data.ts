import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { performance } from "perf_hooks";

const bodySchema = z.object({
  perturbedCentralGeneId: z.number().nullable(),
  targetCentralGeneId: z.number().nullable(),
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

    const ROW_LIMIT = 200;

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
      const params: Array<string> = [];

      // Build subqueries on link tables using indexed central_gene_id lookups.
      // When both are provided, INTERSECT ensures rows match both genes.
      const subqueries: string[] = [];
      if (perturbedCentralGeneId) {
        subqueries.push(`SELECT id FROM ${perturbedLT} WHERE central_gene_id = ?`);
        params.push(String(perturbedCentralGeneId));
      }
      if (targetCentralGeneId) {
        subqueries.push(`SELECT id FROM ${targetLT} WHERE central_gene_id = ?`);
        params.push(String(targetCentralGeneId));
      }

      const idSubquery = subqueries.length === 1
        ? subqueries[0]
        : subqueries.join(" INTERSECT ");
      const fromAndWhere = `FROM ${baseTable} b WHERE b.id IN (${idSubquery})`;

      try {
        // Fetch one extra row to detect whether more rows exist beyond the limit
        const dataSql = `SELECT DISTINCT ${selectCols} ${fromAndWhere} LIMIT ${ROW_LIMIT + 1}`;

        // Query plan
        const plan = db.prepare(`EXPLAIN QUERY PLAN ${dataSql}`).all(...params);
        console.log(`[gene-pair-data] table=${baseTable} QUERY PLAN:`, JSON.stringify(plan));

        const tq = performance.now();
        const allRows = db.prepare(dataSql).all(...params) as Record<string, unknown>[];
        const queryMs = performance.now() - tq;
        console.log(`[gene-pair-data] table=${baseTable} SELECT rows=${allRows.length} time=${queryMs.toFixed(1)}ms`);

        if (allRows.length === 0) continue;

        const hasMore = allRows.length > ROW_LIMIT;
        const rows = hasMore ? allRows.slice(0, ROW_LIMIT) : allRows;

        // Only run the expensive COUNT query when there are more rows than the limit
        let totalRows: number;
        if (hasMore) {
          const countSql = `SELECT COUNT(*) as cnt FROM (SELECT DISTINCT ${selectCols} ${fromAndWhere})`;
          const tc = performance.now();
          totalRows = (db.prepare(countSql).get(...params) as { cnt: number }).cnt;
          const countMs = performance.now() - tc;
          console.log(`[gene-pair-data] table=${baseTable} COUNT=${totalRows} time=${countMs.toFixed(1)}ms`);
        } else {
          totalRows = rows.length;
        }

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
          rows,
          totalRows,
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
