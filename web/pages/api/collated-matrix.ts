import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb, tableExists } from "@/lib/db";
import { setReadCacheHeaders } from "@/lib/cache-headers";
import { sanitizeIdentifier, parseLinkTablesForDirection } from "@/lib/gene-query";
import {
  compareGeneRows,
  type CellStatus,
  type CollatedMatrixResponse,
  type MatrixCellValue,
  type MatrixColumn,
  type MatrixGeneRow,
  type MatrixSection,
  type MatrixStatusCell,
} from "@/lib/collated-matrix-types";

/**
 * GET /api/collated-matrix — the collated cross-modality overview table
 * ("red table", epic #220).
 *
 * Reads the materialization that `sspsygene overview-matrix` writes into its own
 * file (sspsygene-overview.db, ATTACHed as `overview` — #222) rather than
 * aggregating live: the live version took ~6.8 s for the status columns alone,
 * and the RNA-expression expansion would have added ~5.6 s on top. Everything
 * this endpoint returns is precomputed in `overview.overview_matrix_*`; the work
 * here is assembly.
 *
 * Rows are every experimentally perturbed gene (a central gene in a `perturbed`
 * link table of an `overview_matrix`-labeled dataset, controls excluded).
 * Columns come in two flavours — see @/lib/collated-matrix-types for the
 * contract. A modality flagged `overview_matrix_expand` fans out into one
 * p-value sub-column per measured target gene; the rest stay single status
 * columns.
 *
 * Query params:
 *   expressionMinRegions — a target gene is a sub-column when it is
 *     FDR-significant across at least this many distinct perturbed-side groups
 *     (CNV regions, for the ASD organoid table). Default 3 (232 columns today);
 *     it cannot go below the build floor, which is 1 by default.
 *   expressionMaxColumns — safety cap on the fan-out. At the lowest threshold
 *     the axis is ~4,700 columns / ~545k cells, which is a multi-megabyte
 *     response; columns beyond the cap are dropped strongest-first and
 *     `meta.expressionColumnsTruncated` says so.
 *
 * Degradation: when the overview DB isn't attached (never built, or a pre-#222
 * instance), the status columns are computed live (the fallback kept below) and
 * expanded sections simply don't appear. `meta.materialized` distinguishes the
 * two. A DB with no modality taxonomy at all yields an empty matrix. Neither
 * 500s.
 */

export type { CellStatus };

const querySchema = z.object({
  expressionMinRegions: z.coerce.number().int().min(1).max(10).default(3),
  expressionMaxColumns: z.coerce.number().int().min(1).max(5_000).default(1_500),
});

interface ModalityRow {
  key: string;
  label: string;
  assay_types: string;
  always_show: number;
}

interface Modality {
  key: string;
  label: string;
  alwaysShow: boolean;
  assayTypes: string[];
}

/** Per (gene, modality) accumulator used only by the live fallback. */
interface Accum {
  nSig: number;
  nData: number;
  nAssayed: number;
  tableNames: Set<string>;
}

const NO_DATA: MatrixStatusCell = { status: "none", count: 0, tableNames: [] };

function loadModalities(db: ReturnType<typeof getDb>): Modality[] {
  let rows: ModalityRow[] = [];
  try {
    rows = db
      .prepare(
        "SELECT key, label, assay_types, always_show FROM modalities " +
          "ORDER BY sort_order ASC"
      )
      .all() as ModalityRow[];
  } catch {
    // Older DB build without the #211 taxonomy — an empty matrix beats a 500.
    return [];
  }
  return rows.map((m) => ({
    key: m.key,
    label: m.label,
    alwaysShow: Boolean(m.always_show),
    assayTypes: (() => {
      try {
        return JSON.parse(m.assay_types) as string[];
      } catch {
        return [];
      }
    })(),
  }));
}

/**
 * Pre-#222 live aggregation, kept as the fallback for DBs built before the
 * materialization existed. One grouped, set-based pass per (labeled table,
 * perturbed link table); significance is `< 0.05` over the p-value and FDR
 * columns, matching significant-rows.ts. Slow (~6.8 s) by nature — this is the
 * whole reason the materializer exists.
 */
function computeLiveStatusMatrix(
  db: ReturnType<typeof getDb>,
  modalities: Modality[]
): { genes: MatrixGeneRow[]; statusCells: Map<number, Map<string, MatrixStatusCell>> } {
  if (modalities.length === 0) return { genes: [], statusCells: new Map() };

  const assayToModalities = new Map<string, string[]>();
  for (const m of modalities) {
    for (const a of m.assayTypes) {
      const list = assayToModalities.get(a) ?? [];
      list.push(m.key);
      assayToModalities.set(a, list);
    }
  }

  let tables: Array<{
    table_name: string;
    assay: string | null;
    pvalue_column: string | null;
    fdr_column: string | null;
    link_tables: string | null;
  }>;
  try {
    tables = db
      .prepare(
        `SELECT table_name, assay, pvalue_column, fdr_column, link_tables
           FROM data_tables
          WHERE include_in_overview_matrix = 1`
      )
      .all() as typeof tables;
  } catch {
    // Pre-#212 DB: no opt-in column, so nothing can be a matrix source.
    return { genes: [], statusCells: new Map() };
  }

  const geneAccum = new Map<number, Map<string, Accum>>();
  const geneUniverse = new Set<number>();

  for (const t of tables) {
    const linkTables = parseLinkTablesForDirection(
      t.link_tables || "",
      "perturbed"
    );
    if (linkTables.length === 0) continue;

    const modalityKeys = new Set<string>();
    for (const a of (t.assay || "").split(",").map((s) => s.trim()).filter(Boolean)) {
      for (const k of assayToModalities.get(a) ?? []) modalityKeys.add(k);
    }
    if (modalityKeys.size === 0) continue;

    const statCols: string[] = [];
    for (const raw of [t.pvalue_column, t.fdr_column]) {
      if (!raw) continue;
      for (const c of raw.split(",").map((s) => s.trim()).filter(Boolean)) {
        try {
          statCols.push(sanitizeIdentifier(c));
        } catch {
          /* skip unusable column */
        }
      }
    }

    let baseTable: string;
    try {
      baseTable = sanitizeIdentifier(t.table_name);
    } catch {
      continue;
    }

    const dataPredicate = statCols.length
      ? statCols.map((c) => `t.${c} IS NOT NULL`).join(" OR ")
      : "0";
    const sigPredicate = statCols.length
      ? statCols.map((c) => `(t.${c} IS NOT NULL AND t.${c} < 0.05)`).join(" OR ")
      : "0";

    for (const lt of linkTables) {
      let rows: Array<{
        gene_id: number;
        n_assayed: number;
        n_data: number;
        n_sig: number;
      }>;
      try {
        rows = db
          .prepare(
            `SELECT lt.central_gene_id AS gene_id,
                    COUNT(*) AS n_assayed,
                    SUM(CASE WHEN (${dataPredicate}) THEN 1 ELSE 0 END) AS n_data,
                    SUM(CASE WHEN (${sigPredicate}) THEN 1 ELSE 0 END) AS n_sig
               FROM ${baseTable} t
               JOIN ${lt} lt ON t.id = lt.id
               JOIN central_gene cg ON cg.id = lt.central_gene_id
              WHERE cg.kind != 'control'
              GROUP BY lt.central_gene_id`
          )
          .all() as typeof rows;
      } catch (innerErr) {
        console.error(
          `collated-matrix: query failed for ${baseTable} / ${lt}`,
          innerErr
        );
        continue;
      }

      for (const r of rows) {
        geneUniverse.add(r.gene_id);
        let perModality = geneAccum.get(r.gene_id);
        if (!perModality) {
          perModality = new Map();
          geneAccum.set(r.gene_id, perModality);
        }
        for (const mk of modalityKeys) {
          let acc = perModality.get(mk);
          if (!acc) {
            acc = { nSig: 0, nData: 0, nAssayed: 0, tableNames: new Set() };
            perModality.set(mk, acc);
          }
          acc.nSig += r.n_sig;
          acc.nData += r.n_data;
          acc.nAssayed += r.n_assayed;
          acc.tableNames.add(t.table_name);
        }
      }
    }
  }

  const geneIds = [...geneUniverse];
  const symbolById = new Map<number, string | null>();
  if (geneIds.length > 0) {
    const placeholders = geneIds.map(() => "?").join(",");
    const symRows = db
      .prepare(
        `SELECT id, human_symbol FROM central_gene WHERE id IN (${placeholders})`
      )
      .all(...geneIds) as Array<{ id: number; human_symbol: string | null }>;
    for (const s of symRows) symbolById.set(s.id, s.human_symbol);
  }

  const statusCells = new Map<number, Map<string, MatrixStatusCell>>();
  for (const [geneId, perModality] of geneAccum) {
    const cells = new Map<string, MatrixStatusCell>();
    for (const [modalityKey, acc] of perModality) {
      const tableNames = [...acc.tableNames].sort();
      if (acc.nSig > 0) {
        cells.set(modalityKey, {
          status: "significant",
          count: acc.nSig,
          tableNames,
        });
      } else if (acc.nData > 0) {
        cells.set(modalityKey, { status: "data", count: acc.nData, tableNames });
      } else if (acc.nAssayed > 0) {
        cells.set(modalityKey, {
          status: "assayed_null",
          count: acc.nAssayed,
          tableNames,
        });
      }
    }
    statusCells.set(geneId, cells);
  }

  const genes: MatrixGeneRow[] = geneIds.map((id) => ({
    centralGeneId: id,
    humanSymbol: symbolById.get(id) ?? null,
    cells: {},
  }));
  return { genes, statusCells };
}

/** Read the materialized rows + status cells. */
function readMaterializedStatusMatrix(db: ReturnType<typeof getDb>): {
  genes: MatrixGeneRow[];
  statusCells: Map<number, Map<string, MatrixStatusCell>>;
} {
  const genes = (
    db
      .prepare(
        "SELECT central_gene_id, human_symbol FROM overview.overview_matrix_genes"
      )
      .all() as Array<{ central_gene_id: number; human_symbol: string | null }>
  ).map((r) => ({
    centralGeneId: r.central_gene_id,
    humanSymbol: r.human_symbol,
    cells: {} as Record<string, MatrixCellValue>,
  }));

  const statusCells = new Map<number, Map<string, MatrixStatusCell>>();
  for (const r of db
    .prepare(
      "SELECT central_gene_id, modality_key, status, count, table_names " +
        "FROM overview.overview_matrix_status_cells"
    )
    .all() as Array<{
    central_gene_id: number;
    modality_key: string;
    status: CellStatus;
    count: number;
    table_names: string;
  }>) {
    let perModality = statusCells.get(r.central_gene_id);
    if (!perModality) {
      perModality = new Map();
      statusCells.set(r.central_gene_id, perModality);
    }
    let tableNames: string[];
    try {
      tableNames = JSON.parse(r.table_names) as string[];
    } catch {
      tableNames = [];
    }
    perModality.set(r.modality_key, {
      status: r.status,
      count: r.count,
      tableNames,
    });
  }
  return { genes, statusCells };
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const parsed = querySchema.safeParse(req.query);
  if (!parsed.success) {
    return res.status(400).json({ error: "Invalid query parameters" });
  }
  const { expressionMaxColumns } = parsed.data;

  try {
    const db = getDb();
    const modalities = loadModalities(db);
    // #222 moved the materialization into its own file (sspsygene-overview.db),
    // ATTACHed as `overview` by getDb(). Absent attach → live fallback below.
    const materialized = tableExists(db, "overview_matrix_genes", "overview");

    const { genes, statusCells } = materialized
      ? readMaterializedStatusMatrix(db)
      : computeLiveStatusMatrix(db, modalities);
    genes.sort(compareGeneRows);

    const info = materialized
      ? new Map(
          (
            db
              .prepare("SELECT key, value FROM overview.overview_matrix_info")
              .all() as Array<{ key: string; value: string }>
          ).map((r) => [r.key, r.value])
        )
      : new Map<string, string>();
    const floor = Math.max(1, Number(info.get("min_groups_floor") ?? 1) || 1);
    // The build decides how deep the fan-out can go; a request can only ask for
    // the same threshold or a stricter one.
    const minRegions = Math.max(parsed.data.expressionMinRegions, floor);

    // Which modalities are expanded, and under what cell-key prefix.
    const expansions = materialized
      ? (
          db
            .prepare(
              "SELECT modality_key, column_prefix FROM overview.overview_matrix_expansions"
            )
            .all() as Array<{ modality_key: string; column_prefix: string }>
        ).reduce(
          (acc, r) => acc.set(r.modality_key, r.column_prefix),
          new Map<string, string>()
        )
      : new Map<string, string>();

    const sections: MatrixSection[] = [];
    const columns: MatrixColumn[] = [];
    let expressionColumnCount = 0;
    let expressionColumnsAvailable = 0;

    for (const modality of modalities) {
      const prefix = expansions.get(modality.key);
      if (prefix === undefined) {
        // Status section: one column, keyed by the modality itself so
        // `cells[modalityKey]` keeps its original meaning.
        for (const gene of genes) {
          gene.cells[modality.key] =
            statusCells.get(gene.centralGeneId)?.get(modality.key) ?? NO_DATA;
        }
        const isEmpty = !genes.some(
          (g) => (g.cells[modality.key] as MatrixStatusCell).status !== "none"
        );
        sections.push({
          key: modality.key,
          label: modality.label,
          kind: "status",
          span: 1,
          alwaysShow: modality.alwaysShow,
          isEmpty,
        });
        columns.push({
          section: modality.key,
          key: modality.key,
          label: modality.label,
          kind: "status",
        });
        continue;
      }

      // Expanded section: the qualifying target genes, strongest first.
      const available = db
        .prepare(
          "SELECT COUNT(*) AS n FROM overview.overview_matrix_expanded_columns " +
            "WHERE modality_key = ? AND n_sig_regions >= ?"
        )
        .get(modality.key, minRegions) as { n: number };
      const columnRows = db
        .prepare(
          "SELECT column_value, n_sig_regions FROM overview.overview_matrix_expanded_columns " +
            "WHERE modality_key = ? AND n_sig_regions >= ? " +
            "ORDER BY sort_rank ASC LIMIT ?"
        )
        .all(modality.key, minRegions, expressionMaxColumns) as Array<{
        column_value: string;
        n_sig_regions: number;
      }>;

      for (const row of columnRows) {
        columns.push({
          section: modality.key,
          key: `${prefix}:${row.column_value}`,
          label: row.column_value,
          kind: "pvalue",
          nSigRegions: row.n_sig_regions,
        });
      }

      if (columnRows.length > 0) {
        const byId = new Map(genes.map((g) => [g.centralGeneId, g]));
        // Join against the same selection rather than fetching every
        // materialized cell and filtering here: at the build floor that would
        // be ~545k rows to reach the ~27k this response needs.
        // `.raw()` yields plain arrays: this is the one genuinely hot loop in
        // the handler (tens of thousands of cells), and skipping a row object
        // per cell is worth the positional access.
        for (const [geneId, columnValue, negLogP] of db
          .prepare(
            // CROSS JOIN is the join-order hint, not a cartesian product:
            // left to itself SQLite scans every cell of the modality and
            // probes the column list (~80 ms), instead of seeking the ~230
            // selected columns in the column-clustered cell table (~2 ms).
            `SELECT c.central_gene_id, c.column_value, c.neg_log_p
               FROM (SELECT column_value FROM overview.overview_matrix_expanded_columns
                      WHERE modality_key = ? AND n_sig_regions >= ?
                      ORDER BY sort_rank ASC LIMIT ?) k
               CROSS JOIN overview.overview_matrix_expanded_cells c
                 ON c.modality_key = ? AND c.column_value = k.column_value`
          )
          .raw()
          .all(
            modality.key,
            minRegions,
            expressionMaxColumns,
            modality.key
          ) as Array<[number, string, number]>) {
          const gene = byId.get(geneId);
          if (!gene) continue;
          gene.cells[`${prefix}:${columnValue}`] = { negLogP };
        }
      }

      sections.push({
        key: modality.key,
        label: modality.label,
        kind: "expanded",
        span: columnRows.length,
        alwaysShow: modality.alwaysShow,
        isEmpty: columnRows.length === 0,
      });
      expressionColumnCount += columnRows.length;
      expressionColumnsAvailable += available.n;
    }

    const body: CollatedMatrixResponse = {
      sections,
      columns,
      genes,
      meta: {
        expressionMinRegions: minRegions,
        expressionColumnCount,
        expressionColumnsAvailable,
        expressionColumnsTruncated:
          expressionColumnCount < expressionColumnsAvailable,
        expressionMinRegionsFloor: floor,
        materialized,
        builtAt: info.get("built_at") ?? null,
      },
    };

    setReadCacheHeaders(res);
    return res.status(200).json(body);
  } catch (err) {
    console.error("collated-matrix handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
