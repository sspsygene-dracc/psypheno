import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { setReadCacheHeaders } from "@/lib/cache-headers";
import { buildGeneQuery, ALL_CONTROLS_SENTINEL_ID } from "@/lib/gene-query";
import { getVolcanoBackground } from "@/lib/volcano-background";

// IDs are non-negative auto-increment ints in central_gene, plus the
// reserved sentinel for "all controls" — accept either, reject anything
// else by lower-bounding at the sentinel.
const bodySchema = z.object({
  tableName: z.string().regex(/^[A-Za-z0-9_]+$/),
  perturbedCentralGeneId: z.number().int().min(ALL_CONTROLS_SENTINEL_ID).optional(),
  targetCentralGeneId: z.number().int().min(ALL_CONTROLS_SENTINEL_ID).optional(),
});

type GeneRow = {
  effect: number | null;
  pvalue: number | null;
  fdr: number | null;
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
  const { tableName, perturbedCentralGeneId, targetCentralGeneId } = parse.data;

  try {
    const db = getDb();

    // Everything except the orange-dot gene rows is independent of the
    // target gene and cached per table (lib/volcano-background.ts).
    const result = getVolcanoBackground(db, tableName, perturbedCentralGeneId);
    if (!result.ok) {
      return res.status(404).json({ error: result.error });
    }
    const bg = result.background;
    const { baseTable, displayCols, linkTablesRaw, effectCol, pvalueCol, fdrCol } = bg;

    // Orange-dot rows highlight the *target* gene (per #152). When only a
    // perturbed gene is given, the background already represents that
    // perturbation's experiment — there's no separate row to single out.
    // When both are given, intersect (target row WITHIN the perturbation's
    // background); same as gene-data's pair-search semantics.
    const geneRows: GeneRow[] = [];
    if (targetCentralGeneId) {
      const query = buildGeneQuery({
        baseTable,
        displayCols,
        linkTablesRaw,
        perturbedCentralGeneId,
        targetCentralGeneId,
      });
      if (query) {
        const fdrSelectGene = fdrCol ? `, b.${fdrCol} AS fdr` : `, NULL AS fdr`;
        const sql = `SELECT DISTINCT b.id, b.${effectCol} AS effect, b.${pvalueCol} AS pvalue${fdrSelectGene} ${query.fromAndWhere}`;
        const rows = db.prepare(sql).all(...query.params) as Array<{
          id: number;
          effect: number | null;
          pvalue: number | null;
          fdr: number | null;
        }>;
        for (const r of rows) {
          geneRows.push({
            effect: r.effect == null ? null : Number(r.effect),
            pvalue: r.pvalue == null ? null : Number(r.pvalue),
            fdr: r.fdr == null ? null : Number(r.fdr),
            rowKey: String(r.id),
          });
        }
      }
    }

    setReadCacheHeaders(res);
    return res.status(200).json({
      effectColumn: bg.effectColumn,
      // pvalueColumn names the y-axis source — when the table only ships
      // FDR, that's `qval`/etc., and the frontend renders `-log10(qval)`.
      pvalueColumn: pvalueCol,
      fdrColumn: bg.fdrColumn,
      nTotal: bg.nNonNull,
      nNonNull: bg.nNonNull,
      // Which gene a tooltip link should search by: "target" → /?target=SYM,
      // "perturbed" → /?perturbed=SYM. null when the table has no single
      // labelling link table (#189).
      labelDirection: bg.labelDirection,
      volcanoPoints: bg.volcanoPoints,
      geneRows,
      fieldLabels: bg.fieldLabels,
    });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("effect-distribution handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
