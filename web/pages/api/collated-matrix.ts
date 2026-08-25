import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb, tableExists } from "@/lib/db";
import { setReadCacheHeaders } from "@/lib/cache-headers";
import {
  compareGeneRows,
  type CollatedMatrixResponse,
  type MatrixCell,
  type MatrixColumn,
  type MatrixGeneRow,
  type MatrixMode,
  type MatrixSection,
  type MetricPresence,
} from "@/lib/collated-matrix-types";

/**
 * GET /api/collated-matrix — the collated cross-modality overview table
 * ("red table", epic #220, #213).
 *
 * Reads the materialization that `sspsygene overview-matrix` writes into its own
 * file (sspsygene-overview.db, ATTACHed as `overview`) rather than aggregating
 * live. Every modality is expanded into value columns (there are no aggregated
 * "status" columns anymore); each column carries a `metric` naming its color
 * scale and each cell a `value` in that metric's units. Rows are every
 * experimentally perturbed gene.
 *
 * Query param `colsPerDataset` (K) caps how many columns each dataset shows (top
 * K by convergence / gene count). Default 25, max 200 (the build materializes
 * the top ~200 per dataset). Gene-target eligibility (FDR-significant in ≥N
 * perturbations) is fixed at build time; phenotype datasets show all columns.
 *
 * Query param `mode=summary` (#234) serves the collapsed view instead: one column
 * per dataset, whose cell counts how many of that dataset's readouts came back
 * significant for the gene. That count is materialized over *every* readout, so
 * it is not reachable by asking for `colsPerDataset=1` — K picks the same top-K
 * columns for every row, and those are already filtered to the ones that converge
 * across ≥N perturbations. Colored on log10(1 + n), since counts span 1 → ~3000.
 *
 * Degradation: when the overview DB isn't attached (never built), the matrix is
 * empty (`meta.materialized:false`) rather than 500ing.
 */

const querySchema = z.object({
  colsPerDataset: z.coerce.number().int().min(1).max(200).default(25),
  mode: z.enum(["expanded", "summary"]).default("expanded"),
});

/** Color-scale id for a summary column — see web/lib/matrix-color-scales.ts. */
const SUMMARY_METRIC = "sig_readouts";

/**
 * Dataset band label = the "Author Year" prefix of `medium_label` (curated as
 * "<Author> <Year> - <description>"). Falls back to the short label / table name.
 */
function authorYearLabel(mediumLabel: string | null, fallback: string): string {
  const head = (mediumLabel ?? "").split(" - ")[0].trim();
  return head || fallback;
}

interface ModalityRow {
  key: string;
  label: string;
}

function loadModalities(db: ReturnType<typeof getDb>): ModalityRow[] {
  try {
    return db
      .prepare("SELECT key, label FROM modalities ORDER BY sort_order ASC")
      .all() as ModalityRow[];
  } catch {
    return [];
  }
}

function parseDomain(raw: string | null): [number, number] | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (
      Array.isArray(parsed) &&
      parsed.length === 2 &&
      typeof parsed[0] === "number" &&
      typeof parsed[1] === "number"
    ) {
      return [parsed[0], parsed[1]];
    }
  } catch {
    /* fall through */
  }
  return null;
}

function emptyResponse(K: number, mode: MatrixMode): CollatedMatrixResponse {
  return {
    sections: [],
    columns: [],
    genes: [],
    meta: {
      mode,
      summaryAvailable: false,
      colsPerDataset: K,
      expandedColumnCount: 0,
      expandedColumnsAvailable: 0,
      expandedColumnsTruncated: false,
      minSigGroupsFloor: 2,
      materializeTopM: 200,
      materialized: false,
      builtAt: null,
      metrics: [],
    },
  };
}

interface SummaryColumnRow {
  source_table: string;
  modality_key: string;
  column_prefix: string;
  source_label: string | null;
  base_metric: string;
  sig_rule: string;
  n_readouts_total: number;
}

/**
 * The collapsed view (#234): one column per dataset, cell = how many of that
 * dataset's readouts were significant for the gene.
 *
 * Shape-compatible with the expanded response on purpose — the canvas, the
 * clustering and the dataset hide/unhide all keep working on a `MatrixColumn`
 * without knowing which view produced it.
 */
function buildSummaryResponse(args: {
  db: ReturnType<typeof getDb>;
  genes: MatrixGeneRow[];
  byId: Map<number, MatrixGeneRow>;
  modalities: ModalityRow[];
  datasetMeta: Map<string, { mediumLabel: string | null; citation: string | null }>;
  floor: number;
  topM: number;
  builtAt: string | null;
  K: number;
}): CollatedMatrixResponse {
  const { db, genes, byId, modalities, datasetMeta, floor, topM, builtAt, K } = args;

  const rows = db
    .prepare(
      "SELECT source_table, modality_key, column_prefix, source_label, " +
        " base_metric, sig_rule, n_readouts_total " +
        "FROM overview.overview_matrix_summary_columns " +
        "ORDER BY source_label ASC, source_table ASC"
    )
    .all() as SummaryColumnRow[];

  // Author-year alone stops being an identity once a whole dataset is one
  // column: Zheng 2024 ships two tables and Gordon 2026 two more, so a bare
  // author-year would label two adjacent columns identically. Fall back to the
  // dataset's short label only for the ones that actually collide.
  const authorYear = new Map<string, string>();
  const collisions = new Map<string, number>();
  for (const r of rows) {
    const label = authorYearLabel(
      datasetMeta.get(r.source_table)?.mediumLabel ?? null,
      r.source_label ?? r.source_table
    );
    authorYear.set(r.source_table, label);
    collisions.set(label, (collisions.get(label) ?? 0) + 1);
  }
  const labelFor = (r: SummaryColumnRow): string => {
    const base = authorYear.get(r.source_table) ?? r.source_table;
    if ((collisions.get(base) ?? 0) <= 1 || !r.source_label) return base;
    // `short_label` is a snake_case slug; the header reads it as words.
    return `${base} · ${r.source_label.replace(/_/g, " ")}`;
  };

  // Section order from the modality taxonomy; anything not in it renders after.
  const knownKeys = modalities.map((m) => m.key);
  const presentKeys = [...new Set(rows.map((r) => r.modality_key))];
  const orderedKeys = [
    ...knownKeys.filter((k) => presentKeys.includes(k)),
    ...presentKeys.filter((k) => !knownKeys.includes(k)),
  ];
  const labelByModality = new Map(modalities.map((m) => [m.key, m.label]));

  const columns: MatrixColumn[] = [];
  const sections: MatrixSection[] = [];
  for (const modalityKey of orderedKeys) {
    const inSection = rows.filter((r) => r.modality_key === modalityKey);
    if (inSection.length === 0) continue;
    for (const r of inSection) {
      const dsMeta = datasetMeta.get(r.source_table) ?? {
        mediumLabel: null,
        citation: null,
      };
      const label = labelFor(r);
      columns.push({
        section: modalityKey,
        key: `${r.column_prefix}:${r.source_table}:__summary__`,
        label,
        metric: SUMMARY_METRIC,
        columnIsGene: false,
        nSigGroups: r.n_readouts_total,
        sourceTable: r.source_table,
        sourceLabel: label,
        sourceMediumLabel: dsMeta.mediumLabel,
        sourceCitation: dsMeta.citation,
        baseMetric: r.base_metric,
        sigRule: r.sig_rule,
      });
    }
    sections.push({
      key: modalityKey,
      label: labelByModality.get(modalityKey) ?? modalityKey,
      span: inSection.length,
    });
  }

  const keyByTable = new Map(columns.map((c) => [c.sourceTable, c.key]));
  for (const [sourceTable, geneId, nSig, nMeasured, best] of db
    .prepare(
      "SELECT source_table, central_gene_id, n_sig, n_measured, best_value " +
        "FROM overview.overview_matrix_summary_cells"
    )
    .raw()
    .all() as Array<[string, number, number, number, number]>) {
    const gene = byId.get(geneId);
    const key = keyByTable.get(sourceTable);
    if (!gene || key === undefined) continue;
    // log10(1 + n). Counts span 1 → ~3000 across datasets, so a linear ramp
    // would pin everything but the densest DE screens at the bottom of the bar.
    gene.cells[key] = {
      value: Math.round(Math.log10(1 + nSig) * 1000) / 1000,
      nSig,
      nMeasured,
      best,
    };
  }

  return {
    sections,
    columns,
    genes,
    meta: {
      mode: "summary",
      summaryAvailable: true,
      colsPerDataset: K,
      expandedColumnCount: columns.length,
      expandedColumnsAvailable: columns.length,
      expandedColumnsTruncated: false,
      minSigGroupsFloor: floor,
      materializeTopM: topM,
      materialized: true,
      builtAt,
      metrics: [{ id: SUMMARY_METRIC, domain: null }],
    },
  };
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
  const mode = parsed.data.mode;

  try {
    const db = getDb();
    // The materialization lives in its own file (sspsygene-overview.db), ATTACHed
    // as `overview` by getDb(). Absent → empty matrix, never a 500.
    if (!tableExists(db, "overview_matrix_genes", "overview")) {
      setReadCacheHeaders(res);
      return res.status(200).json(emptyResponse(K, mode));
    }
    // Reported on both paths so the page can disable the Summary control against
    // an overview DB built before #234, instead of showing an empty matrix.
    const summaryAvailable = tableExists(
      db,
      "overview_matrix_summary_columns",
      "overview"
    );
    if (mode === "summary" && !summaryAvailable) {
      setReadCacheHeaders(res);
      return res.status(200).json(emptyResponse(K, mode));
    }

    const genes: MatrixGeneRow[] = (
      db
        .prepare(
          "SELECT central_gene_id, human_symbol FROM overview.overview_matrix_genes"
        )
        .all() as Array<{ central_gene_id: number; human_symbol: string | null }>
    ).map((r) => ({
      centralGeneId: r.central_gene_id,
      humanSymbol: r.human_symbol,
      cells: {} as Record<string, MatrixCell>,
    }));
    genes.sort(compareGeneRows);
    const byId = new Map(genes.map((g) => [g.centralGeneId, g]));

    const info = new Map(
      (
        db
          .prepare("SELECT key, value FROM overview.overview_matrix_info")
          .all() as Array<{ key: string; value: string }>
      ).map((r) => [r.key, r.value])
    );
    const floor = Math.max(1, Number(info.get("min_groups_floor") ?? 2) || 2);
    const topM = Math.max(1, Number(info.get("materialize_top_m") ?? 200) || 200);

    // modality_key → cell-key prefix.
    const prefixByModality = (
      db
        .prepare(
          "SELECT modality_key, column_prefix FROM overview.overview_matrix_expansions"
        )
        .all() as Array<{ modality_key: string; column_prefix: string }>
    ).reduce(
      (acc, r) => acc.set(r.modality_key, r.column_prefix),
      new Map<string, string>()
    );

    // Section order + labels from the modality taxonomy; any expanded modality
    // missing from it still renders (labeled by its key) after the known ones.
    const modalities = loadModalities(db);
    const orderedModalityKeys = [
      ...modalities.filter((m) => prefixByModality.has(m.key)).map((m) => m.key),
      ...[...prefixByModality.keys()].filter(
        (k) => !modalities.some((m) => m.key === k)
      ),
    ];
    const labelByModality = new Map(modalities.map((m) => [m.key, m.label]));

    // Fuller dataset identity for the author-year label + band tooltip.
    const datasetMeta = new Map<
      string,
      { mediumLabel: string | null; citation: string | null }
    >();
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

    const sections: MatrixSection[] = [];
    const columns: MatrixColumn[] = [];
    const metrics = new Map<string, [number, number] | null>();
    let expandedColumnCount = 0;
    let expandedColumnsAvailable = 0;

    const srcTablesStmt = db.prepare(
      "SELECT source_table, source_label, COUNT(*) AS available " +
        "FROM overview.overview_matrix_expanded_columns " +
        "WHERE modality_key = ? GROUP BY source_table, source_label " +
        "ORDER BY source_label ASC"
    );
    const colStmt = db.prepare(
      "SELECT column_value, n_sig_groups, metric, metric_domain, column_is_gene " +
        "FROM overview.overview_matrix_expanded_columns " +
        "WHERE modality_key = ? AND source_table = ? ORDER BY sort_rank ASC LIMIT ?"
    );
    const cellStmt = db
      .prepare(
        `SELECT c.central_gene_id, c.column_value, c.value
           FROM (SELECT column_value
                   FROM overview.overview_matrix_expanded_columns
                  WHERE modality_key = ? AND source_table = ?
                  ORDER BY sort_rank ASC LIMIT ?) k
           CROSS JOIN overview.overview_matrix_expanded_cells c
             ON c.modality_key = ? AND c.source_table = ?
                AND c.column_value = k.column_value`
      )
      .raw();

    if (mode === "summary") {
      const body = buildSummaryResponse({
        db,
        genes,
        byId,
        modalities,
        datasetMeta,
        floor,
        topM,
        builtAt: info.get("built_at") ?? null,
        K,
      });
      setReadCacheHeaders(res);
      return res.status(200).json(body);
    }

    for (const modalityKey of orderedModalityKeys) {
      const prefix = prefixByModality.get(modalityKey);
      if (prefix === undefined) continue;

      const srcTables = srcTablesStmt.all(modalityKey) as Array<{
        source_table: string;
        source_label: string | null;
        available: number;
      }>;

      let sectionSpan = 0;
      for (const st of srcTables) {
        const colRows = colStmt.all(modalityKey, st.source_table, K) as Array<{
          column_value: string;
          n_sig_groups: number;
          metric: string;
          metric_domain: string | null;
          column_is_gene: number;
        }>;
        if (colRows.length === 0) continue;

        const dsMeta = datasetMeta.get(st.source_table) ?? {
          mediumLabel: null,
          citation: null,
        };
        const sourceLabel = authorYearLabel(
          dsMeta.mediumLabel,
          st.source_label ?? st.source_table
        );
        for (const row of colRows) {
          const domain = parseDomain(row.metric_domain);
          if (!metrics.has(row.metric)) metrics.set(row.metric, domain);
          else if (domain && !metrics.get(row.metric)) {
            metrics.set(row.metric, domain);
          }
          columns.push({
            section: modalityKey,
            key: `${prefix}:${st.source_table}:${row.column_value}`,
            label: row.column_value,
            metric: row.metric,
            columnIsGene: Boolean(row.column_is_gene),
            nSigGroups: row.n_sig_groups,
            sourceTable: st.source_table,
            sourceLabel,
            sourceMediumLabel: dsMeta.mediumLabel,
            sourceCitation: dsMeta.citation,
          });
        }

        for (const [geneId, columnValue, value] of cellStmt.all(
          modalityKey,
          st.source_table,
          K,
          modalityKey,
          st.source_table
        ) as Array<[number, string, number]>) {
          const gene = byId.get(geneId);
          if (!gene) continue;
          gene.cells[`${prefix}:${st.source_table}:${columnValue}`] = { value };
        }

        sectionSpan += colRows.length;
        expandedColumnCount += colRows.length;
        expandedColumnsAvailable += st.available;
      }

      if (sectionSpan === 0) continue;
      sections.push({
        key: modalityKey,
        label: labelByModality.get(modalityKey) ?? modalityKey,
        span: sectionSpan,
      });
    }

    const metricsPresent: MetricPresence[] = [...metrics.entries()].map(
      ([id, domain]) => ({ id, domain })
    );

    const body: CollatedMatrixResponse = {
      sections,
      columns,
      genes,
      meta: {
        mode,
        summaryAvailable,
        colsPerDataset: K,
        expandedColumnCount,
        expandedColumnsAvailable,
        expandedColumnsTruncated: expandedColumnCount < expandedColumnsAvailable,
        minSigGroupsFloor: floor,
        materializeTopM: topM,
        materialized: true,
        builtAt: info.get("built_at") ?? null,
        metrics: metricsPresent,
      },
    };

    setReadCacheHeaders(res);
    return res.status(200).json(body);
  } catch (err) {
    console.error("collated-matrix handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
