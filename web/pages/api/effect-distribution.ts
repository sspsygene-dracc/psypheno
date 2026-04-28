import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import {
  sanitizeIdentifier,
  parseDisplayColumns,
  buildGeneQuery,
} from "@/lib/gene-query";

const bodySchema = z.object({
  tableName: z.string().regex(/^[A-Za-z0-9_]+$/),
  centralGeneId: z.number().int().min(0).optional(),
  perturbedCentralGeneId: z.number().int().min(0).optional(),
  targetCentralGeneId: z.number().int().min(0).optional(),
  direction: z.enum(["target", "perturbed"]).optional(),
});

type StoredVolcano = { e: number; l: number; t: boolean };

type GeneRow = {
  effect: number | null;
  pvalue: number | null;
  rowKey: string;
};

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse,
) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  const parse = bodySchema.safeParse(req.body);
  if (!parse.success) {
    return res.status(400).json({ error: "Invalid request body" });
  }
  const {
    tableName,
    centralGeneId,
    perturbedCentralGeneId,
    targetCentralGeneId,
    direction,
  } = parse.data;

  try {
    const db = getDb();

    const dist = db
      .prepare(
        `SELECT effect_column, pvalue_column, n_total, n_nonnull,
                bin_edges_json, bin_counts_json, volcano_points_json
         FROM table_effect_distributions WHERE table_name = ?`,
      )
      .get(tableName) as
      | {
          effect_column: string;
          pvalue_column: string;
          n_total: number;
          n_nonnull: number;
          bin_edges_json: string;
          bin_counts_json: string;
          volcano_points_json: string;
        }
      | undefined;

    if (!dist) {
      return res.status(404).json({ error: "No distribution for this table" });
    }

    const binEdges = JSON.parse(dist.bin_edges_json) as number[];
    const binCounts = JSON.parse(dist.bin_counts_json) as number[];
    const volcanoStored = JSON.parse(
      dist.volcano_points_json,
    ) as StoredVolcano[];
    const volcanoPoints = volcanoStored.map((p) => ({
      effect: p.e,
      negLog10P: p.l,
      topByP: p.t,
    }));

    // Look up the queried gene's rows in this table by joining on the link
    // tables — uses the same logic as the main gene-data query.
    const tableMeta = db
      .prepare(
        `SELECT display_columns, link_tables FROM data_tables WHERE table_name = ?`,
      )
      .get(tableName) as
      | { display_columns: string; link_tables: string | null }
      | undefined;

    const geneRows: GeneRow[] = [];
    if (tableMeta) {
      const baseTable = sanitizeIdentifier(tableName);
      const displayCols = parseDisplayColumns(tableMeta.display_columns);
      const effectCol = sanitizeIdentifier(dist.effect_column);
      const pvalueCol = sanitizeIdentifier(dist.pvalue_column.split(",")[0]);
      if (
        displayCols.includes(effectCol) &&
        displayCols.includes(pvalueCol)
      ) {
        const query = buildGeneQuery({
          baseTable,
          displayCols,
          linkTablesRaw: tableMeta.link_tables || "",
          centralGeneId,
          direction,
          perturbedCentralGeneId,
          targetCentralGeneId,
        });
        if (query) {
          const sql = `SELECT DISTINCT b.id, b.${effectCol} AS effect, b.${pvalueCol} AS pvalue ${query.fromAndWhere}`;
          const rows = db.prepare(sql).all(...query.params) as Array<{
            id: number;
            effect: number | null;
            pvalue: number | null;
          }>;
          for (const r of rows) {
            geneRows.push({
              effect: r.effect == null ? null : Number(r.effect),
              pvalue: r.pvalue == null ? null : Number(r.pvalue),
              rowKey: String(r.id),
            });
          }
        }
      }
    }

    return res.status(200).json({
      effectColumn: dist.effect_column,
      pvalueColumn: dist.pvalue_column,
      nTotal: dist.n_total,
      nNonNull: dist.n_nonnull,
      histogram: { binEdges, binCounts },
      volcanoPoints,
      geneRows,
    });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("effect-distribution handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
