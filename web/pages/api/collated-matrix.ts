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
 * Degradation: when the overview DB isn't attached (never built), the matrix is
 * empty (`meta.materialized:false`) rather than 500ing.
 */

const querySchema = z.object({
  colsPerDataset: z.coerce.number().int().min(1).max(200).default(25),
});

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

function emptyResponse(K: number): CollatedMatrixResponse {
  return {
    sections: [],
    columns: [],
    genes: [],
    meta: {
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
    // The materialization lives in its own file (sspsygene-overview.db), ATTACHed
    // as `overview` by getDb(). Absent → empty matrix, never a 500.
    if (!tableExists(db, "overview_matrix_genes", "overview")) {
      setReadCacheHeaders(res);
      return res.status(200).json(emptyResponse(K));
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
