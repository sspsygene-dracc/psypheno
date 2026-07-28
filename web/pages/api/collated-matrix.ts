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
 *   colsPerDataset — how many columns to show per expanded dataset (top K by
 *     convergence). Default 25, max 200 (the build materializes the top ~200
 *     most-convergent per dataset, so K can range freely within that). This is
 *     the one size knob: it bounds the dense CRISPR screens (SCZ arrayed alone
 *     has thousands of eligible target columns) while giving every dataset equal
 *     representation. Eligibility (target FDR-significant in ≥2 perturbations) is
 *     fixed at build time.
 *
 * Degradation: when the overview DB isn't attached (never built, or a pre-#222
 * instance), the status columns are computed live (the fallback kept below) and
 * expanded sections simply don't appear. `meta.materialized` distinguishes the
 * two. A DB with no modality taxonomy at all yields an empty matrix. Neither
 * 500s.
 */

export type { CellStatus };

const querySchema = z.object({
  colsPerDataset: z.coerce.number().int().min(1).max(200).default(25),
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
  const K = parsed.data.colsPerDataset;

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
    const byId = new Map(genes.map((g) => [g.centralGeneId, g]));

    const info = materialized
      ? new Map(
          (
            db
              .prepare("SELECT key, value FROM overview.overview_matrix_info")
              .all() as Array<{ key: string; value: string }>
          ).map((r) => [r.key, r.value])
        )
      : new Map<string, string>();
    const floor = Math.max(1, Number(info.get("min_groups_floor") ?? 2) || 2);
    const topM = Math.max(1, Number(info.get("materialize_top_m") ?? 200) || 200);

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

    // Fuller dataset identity for the per-dataset (i) tooltips, from the main DB.
    const datasetMeta = new Map<
      string,
      { mediumLabel: string | null; citation: string | null }
    >();
    if (materialized) {
      for (const r of db
        .prepare("SELECT table_name, medium_label, source FROM data_tables")
        .all() as Array<{
        table_name: string;
        medium_label: string | null;
        source: string | null;
      }>) {
        datasetMeta.set(r.table_name, {
          mediumLabel: r.medium_label,
          citation: r.source,
        });
      }
    }

    const sections: MatrixSection[] = [];
    const columns: MatrixColumn[] = [];
    let expandedColumnCount = 0;
    let expandedColumnsAvailable = 0;

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

      // Expanded section: fan out each contributing dataset into its top-K
      // most-convergent target columns. Columns are emitted contiguously per
      // dataset so the frontend can render one dataset band per group.
      const srcTables = db
        .prepare(
          "SELECT source_table, source_label, COUNT(*) AS available " +
            "FROM overview.overview_matrix_expanded_columns " +
            "WHERE modality_key = ? GROUP BY source_table, source_label " +
            "ORDER BY source_label ASC"
        )
        .all(modality.key) as Array<{
        source_table: string;
        source_label: string | null;
        available: number;
      }>;

      let sectionSpan = 0;
      for (const st of srcTables) {
        const colRows = db
          .prepare(
            "SELECT column_value, n_sig_groups " +
              "FROM overview.overview_matrix_expanded_columns " +
              "WHERE modality_key = ? AND source_table = ? " +
              "ORDER BY sort_rank ASC LIMIT ?"
          )
          .all(modality.key, st.source_table, K) as Array<{
          column_value: string;
          n_sig_groups: number;
        }>;
        if (colRows.length === 0) continue;

        const dsMeta = datasetMeta.get(st.source_table) ?? {
          mediumLabel: null,
          citation: null,
        };
        for (const row of colRows) {
          columns.push({
            section: modality.key,
            key: `${prefix}:${st.source_table}:${row.column_value}`,
            label: row.column_value,
            kind: "pvalue",
            nSigGroups: row.n_sig_groups,
            sourceTable: st.source_table,
            sourceLabel: st.source_label ?? st.source_table,
            sourceMediumLabel: dsMeta.mediumLabel,
            sourceCitation: dsMeta.citation,
          });
        }

        // Cells for this dataset's top-K. Same CROSS-JOIN join-order hint as
        // before: seek the ~K selected columns in the column-clustered cell
        // table rather than scanning the whole modality. `.raw()` skips a row
        // object per cell in the one hot loop.
        for (const [geneId, columnValue, negLogP] of db
          .prepare(
            `SELECT c.central_gene_id, c.column_value, c.neg_log_p
               FROM (SELECT column_value
                       FROM overview.overview_matrix_expanded_columns
                      WHERE modality_key = ? AND source_table = ?
                      ORDER BY sort_rank ASC LIMIT ?) k
               CROSS JOIN overview.overview_matrix_expanded_cells c
                 ON c.modality_key = ? AND c.source_table = ?
                    AND c.column_value = k.column_value`
          )
          .raw()
          .all(
            modality.key,
            st.source_table,
            K,
            modality.key,
            st.source_table
          ) as Array<[number, string, number]>) {
          const gene = byId.get(geneId);
          if (!gene) continue;
          gene.cells[`${prefix}:${st.source_table}:${columnValue}`] = {
            negLogP,
          };
        }

        sectionSpan += colRows.length;
        expandedColumnCount += colRows.length;
        expandedColumnsAvailable += st.available;
      }

      sections.push({
        key: modality.key,
        label: modality.label,
        kind: "expanded",
        span: sectionSpan,
        alwaysShow: modality.alwaysShow,
        isEmpty: sectionSpan === 0,
      });
    }

    const body: CollatedMatrixResponse = {
      sections,
      columns,
      genes,
      meta: {
        colsPerDataset: K,
        expandedColumnCount,
        expandedColumnsAvailable,
        expandedColumnsTruncated: expandedColumnCount < expandedColumnsAvailable,
        minSigGroupsFloor: floor,
        materializeTopM: topM,
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
