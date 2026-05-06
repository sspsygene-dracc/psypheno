import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { setReadCacheHeaders } from "@/lib/cache-headers";
import {
  sanitizeIdentifier,
  parseDisplayColumns,
  parseLinkTablesForDirection,
  buildGeneQuery,
  ALL_CONTROLS_SENTINEL_ID,
} from "@/lib/gene-query";

// IDs are non-negative auto-increment ints in central_gene, plus the
// reserved sentinel for "all controls" — accept either, reject anything
// else by lower-bounding at the sentinel.
const bodySchema = z.object({
  tableName: z.string().regex(/^[A-Za-z0-9_]+$/),
  perturbedCentralGeneId: z.number().int().min(ALL_CONTROLS_SENTINEL_ID).optional(),
  targetCentralGeneId: z.number().int().min(ALL_CONTROLS_SENTINEL_ID).optional(),
});

// Volcano sample shape: ~100 always-included top-by-p rows + a hash-sorted
// bulk sample. Numbers chosen to match the previous Python precompute so the
// frontend's cloud density looks the same.
const TOP_BY_P_LIMIT = 100;
const BULK_LIMIT = 1000;
const PVALUE_FLOOR = 1e-300;

type VolcanoPoint = {
  effect: number;
  negLog10P: number;
  fdr: number | null;
  topByP: boolean;
};

type SampleRow = {
  id: number;
  effect: number | null;
  pvalue: number | null;
  fdr: number | null;
};

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

    const tableMeta = db
      .prepare(
        `SELECT effect_column, pvalue_column, fdr_column,
                display_columns, link_tables, field_labels
         FROM data_tables WHERE table_name = ?`,
      )
      .get(tableName) as
      | {
          effect_column: string | null;
          pvalue_column: string | null;
          fdr_column: string | null;
          display_columns: string;
          link_tables: string | null;
          field_labels: string | null;
        }
      | undefined;

    // The volcano plot needs an effect column and a y-axis significance
    // column. Prefer raw p-value when available; fall back to FDR when the
    // dataset only ships FDR (e.g. perturb_fish_astro publishes qval but no
    // raw pvalue). The frontend renders `-log10(<column-name>)` from
    // `pvalueColumn`, so it'll say `-log10(qval)` automatically.
    if (
      !tableMeta ||
      !tableMeta.effect_column ||
      (!tableMeta.pvalue_column && !tableMeta.fdr_column)
    ) {
      return res
        .status(404)
        .json({ error: "Table has no effect or significance columns" });
    }

    const baseTable = sanitizeIdentifier(tableName);
    const displayCols = parseDisplayColumns(tableMeta.display_columns);
    const effectCol = sanitizeIdentifier(tableMeta.effect_column);
    const pvalueSource = tableMeta.pvalue_column || tableMeta.fdr_column!;
    const pvalueCol = sanitizeIdentifier(pvalueSource.split(",")[0]);
    const fdrCol = tableMeta.fdr_column
      ? sanitizeIdentifier(tableMeta.fdr_column.split(",")[0])
      : null;

    if (!displayCols.includes(effectCol) || !displayCols.includes(pvalueCol)) {
      return res
        .status(404)
        .json({ error: "effect/significance columns not in display_columns" });
    }

    let fieldLabels: Record<string, string> = {};
    if (tableMeta.field_labels) {
      try {
        const parsed = JSON.parse(tableMeta.field_labels);
        if (parsed && typeof parsed === "object") {
          for (const [k, v] of Object.entries(parsed)) {
            if (typeof v === "string") fieldLabels[k.toLowerCase()] = v;
          }
        }
      } catch {
        fieldLabels = {};
      }
    }

    // Background sample. When a perturbed gene is given AND this table has a
    // perturbed link direction, restrict the sample to that perturbation's
    // rows — the natural "experiment context" for a volcano. Otherwise sample
    // the whole table. The target gene never restricts the background (it
    // would shrink to 1–2 rows, just the orange dot).
    const linkTablesRaw = tableMeta.link_tables || "";
    const perturbedLTs = parseLinkTablesForDirection(linkTablesRaw, "perturbed");
    let backgroundFilter = "";
    const backgroundParams: unknown[] = [];
    const isAllControls = perturbedCentralGeneId === ALL_CONTROLS_SENTINEL_ID;
    if (perturbedCentralGeneId && perturbedLTs.length === 1) {
      if (isAllControls) {
        // "All controls" → restrict the background to control-perturbation
        // rows. Inverse of the default-exclusion below; users searching
        // for controls actively want them.
        backgroundFilter = `AND b.id IN (SELECT lt.id FROM ${perturbedLTs[0]} lt JOIN central_gene cg ON cg.id = lt.central_gene_id WHERE cg.kind = 'control')`;
      } else {
        backgroundFilter = `AND b.id IN (SELECT id FROM ${perturbedLTs[0]} WHERE central_gene_id = ?)`;
        backgroundParams.push(perturbedCentralGeneId);
      }
    }

    // Exclude rows whose perturbed-gene link points at a kind='control'
    // entry (NonTarget1, SafeTarget, GFP, …). Without this, the volcano
    // background in the unrestricted case (no perturbedCentralGeneId, or
    // multiple perturbed link tables) would include control rows and
    // bias the distribution toward "no biological perturbation." Skip
    // when the user is explicitly searching for controls.
    if (!isAllControls) {
      for (const lt of perturbedLTs) {
        backgroundFilter +=
          ` AND b.id NOT IN (` +
          `SELECT lt.id FROM ${lt} lt ` +
          `JOIN central_gene cg ON cg.id = lt.central_gene_id ` +
          `WHERE cg.kind = 'control')`;
      }
    }

    const fdrSelect = fdrCol ? `b.${fdrCol}` : "NULL";
    const baseWhere = `b.${effectCol} IS NOT NULL AND b.${pvalueCol} IS NOT NULL ${backgroundFilter}`;

    // Always include the most-significant rows so the volcano's tails are
    // present regardless of the bulk sample.
    const topSql = `
      SELECT b.id AS id, b.${effectCol} AS effect, b.${pvalueCol} AS pvalue,
             ${fdrSelect} AS fdr
      FROM ${baseTable} b
      WHERE ${baseWhere}
      ORDER BY b.${pvalueCol} ASC
      LIMIT ${TOP_BY_P_LIMIT}
    `;
    // Stable pseudo-random sample: order by Knuth's multiplicative hash of
    // the row id. Deterministic per-DB; breaks insertion-order correlation
    // with effect/pvalue. The mask keeps the value in 31 bits so we never
    // overflow SQLite's int64 expression evaluator.
    const bulkSql = `
      SELECT b.id AS id, b.${effectCol} AS effect, b.${pvalueCol} AS pvalue,
             ${fdrSelect} AS fdr
      FROM ${baseTable} b
      WHERE ${baseWhere}
      ORDER BY ((b.id * 2654435761) & 2147483647)
      LIMIT ${BULK_LIMIT}
    `;
    const topRows = db.prepare(topSql).all(...backgroundParams) as SampleRow[];
    const bulkRows = db.prepare(bulkSql).all(...backgroundParams) as SampleRow[];

    // Dedup by id; top-by-p wins. Compute negLog10P here so SQLite stays
    // free of math.h.
    const seen = new Set<number>();
    const volcanoPoints: VolcanoPoint[] = [];
    const addRow = (row: SampleRow, topByP: boolean) => {
      if (seen.has(row.id)) return;
      if (row.effect == null || row.pvalue == null) return;
      const effect = Number(row.effect);
      const pvalue = Number(row.pvalue);
      if (!Number.isFinite(effect) || !Number.isFinite(pvalue)) return;
      seen.add(row.id);
      volcanoPoints.push({
        effect,
        negLog10P: -Math.log10(Math.max(pvalue, PVALUE_FLOOR)),
        fdr: row.fdr == null ? null : Number(row.fdr),
        topByP,
      });
    };
    for (const r of topRows) addRow(r, true);
    for (const r of bulkRows) addRow(r, false);

    // n_nonnull is the number of rows that *would* contribute to the
    // background — i.e. the size of the (possibly-filtered) population the
    // sample is drawn from. Cheap on filtered queries; on unfiltered ones
    // it's a single scan over rows the sample queries already touched.
    const nNonNull = (
      db
        .prepare(
          `SELECT COUNT(*) AS cnt FROM ${baseTable} b WHERE ${baseWhere}`,
        )
        .get(...backgroundParams) as { cnt: number }
    ).cnt;

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
      effectColumn: tableMeta.effect_column,
      // pvalueColumn names the y-axis source — when the table only ships
      // FDR, that's `qval`/etc., and the frontend renders `-log10(qval)`.
      pvalueColumn: pvalueCol,
      fdrColumn: tableMeta.fdr_column,
      nTotal: nNonNull,
      nNonNull,
      volcanoPoints,
      geneRows,
      fieldLabels,
    });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("effect-distribution handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
