import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb, getMetaStatus } from "@/lib/db";
import { setReadCacheHeaders } from "@/lib/cache-headers";
import {
  sanitizeIdentifier,
  parseLinkTablesForDirection,
} from "@/lib/gene-query";

const bodySchema = z.object({
  centralGeneId: z.number().min(0),
  direction: z.enum(["target", "perturbed"]).optional(),
  regulation: z.enum(["any", "up", "down"]).optional(),
  // Dataset-restrictor facets (assay/condition/organism) the breakdown should
  // subset to. Null = "All" for that facet. Applied on both the home page and
  // /most-significant.
  assayFilter: z.string().regex(/^[a-z0-9_]+$/).nullable().optional(),
  conditionFilter: z.string().regex(/^[a-z0-9_]+$/).nullable().optional(),
  organismFilter: z.string().regex(/^[a-z0-9_]+$/).nullable().optional(),
  // When true (the /most-significant gene expansion), the breakdown is further
  // restricted to the datasets that actually fed the meta-analysis for the
  // selected group, and the combined number comes from that group's table.
  metaAnalysisOnly: z.boolean().optional(),
});

function combinedTableFor(
  direction: "target" | "perturbed",
  regulation: "any" | "up" | "down",
): string {
  const suffix = regulation === "any" ? "" : `_${regulation}`;
  // Combined-p-value tables live in the ATTACHed meta DB (#176), qualified so
  // they never resolve to a stale same-named table in the main DB.
  return `meta.gene_combined_pvalues_${direction}${suffix}`;
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

  const centralGeneId = parse.data.centralGeneId;
  const direction = parse.data.direction ?? "target";
  const regulation = parse.data.regulation ?? "any";
  const assayFilter = parse.data.assayFilter ?? null;
  const conditionFilter = parse.data.conditionFilter ?? null;
  const organismFilter = parse.data.organismFilter ?? null;
  const metaAnalysisOnly = parse.data.metaAnalysisOnly ?? false;

  try {
    const db = getDb();

    // Resolve which combined-pvalue group this breakdown reflects.
    //  - metaAnalysisOnly (/most-significant): the group matching the current
    //    assay/condition/organism/direction/regulation selection. Its
    //    source_table_names is the authoritative set of datasets that fed it
    //    (DEG-only, minus meta_analysis:false tables), and combinedPvalues comes
    //    from that group's table. A null assay/condition/organism naturally
    //    matches the global group.
    //  - otherwise (home page): no meta restriction; the combined number stays
    //    the global meta group and the breakdown list is facet-filtered from
    //    dataset metadata below.
    let combinedTable: string | null = combinedTableFor(direction, regulation);
    let metaSourceSet: Set<string> | null = null;
    if (metaAnalysisOnly && getMetaStatus().attached) {
      try {
        const grp = db
          .prepare(
            `SELECT table_name, source_table_names FROM meta.combined_pvalue_groups
             WHERE assay_filter IS ? AND condition_filter IS ? AND organism_filter IS ?
             AND direction = ? AND regulation = ?`
          )
          .get(
            assayFilter,
            conditionFilter,
            organismFilter,
            direction,
            regulation,
          ) as
          | { table_name: string | null; source_table_names: string | null }
          | undefined;
        combinedTable = grp?.table_name ? `meta.${grp.table_name}` : null;
        metaSourceSet = new Set(
          (grp?.source_table_names ?? "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        );
      } catch {
        // Group lookup failed (meta DB shape mismatch) — fall back to the
        // global table with no source-table restriction.
        metaSourceSet = null;
      }
    }

    // Fetch pre-computed combined p-values for the resolved group from the meta
    // DB. Null when meta isn't computed, or the group has no table (fewer than
    // the minimum contributing tables) — the per-dataset rows below still render.
    type CombinedRow = {
      fisher_pvalue: number | null;
      fisher_fdr: number | null;
      cauchy_pvalue: number | null;
      cauchy_fdr: number | null;
      hmp_pvalue: number | null;
      hmp_fdr: number | null;
      num_tables: number;
      num_pvalues: number;
    };
    let combined: CombinedRow | undefined;
    if (combinedTable && getMetaStatus().attached) {
      try {
        combined = db
          .prepare(
            `SELECT fisher_pvalue, fisher_fdr,
                    cauchy_pvalue, cauchy_fdr, hmp_pvalue, hmp_fdr,
                    num_tables, num_pvalues
             FROM ${combinedTable} WHERE central_gene_id = ?`
          )
          .get(centralGeneId) as CombinedRow | undefined;
      } catch {
        combined = undefined;
      }
    }

    // Fetch all tables that have pvalue/fdr columns
    const tablesWithPvalues = db
      .prepare(
        `SELECT table_name, short_label, medium_label, long_label, description, pvalue_column, fdr_column,
                link_tables, field_labels, assay, condition, organism_key, effect_column
         FROM data_tables
         WHERE pvalue_column IS NOT NULL OR fdr_column IS NOT NULL
         ORDER BY id ASC`
      )
      .all() as Array<{
        table_name: string;
        short_label: string | null;
        medium_label: string | null;
        long_label: string | null;
        description: string | null;
        pvalue_column: string | null;
        fdr_column: string | null;
        link_tables: string | null;
        field_labels: string | null;
        assay: string | null;
        condition: string | null;
        organism_key: string | null;
        effect_column: string | null;
      }>;

    // Does this table pass the current restrictor facets? (home-page path)
    const facetMatch = (t: {
      assay: string | null;
      condition: string | null;
      organism_key: string | null;
    }): boolean => {
      const split = (v: string | null) =>
        v ? v.split(",").map((s) => s.trim()).filter(Boolean) : [];
      if (assayFilter && !split(t.assay).includes(assayFilter)) return false;
      if (conditionFilter && !split(t.condition).includes(conditionFilter))
        return false;
      if (organismFilter && !split(t.organism_key).includes(organismFilter))
        return false;
      return true;
    };

    // For each table, count rows and fetch best p-value/FDR for this gene
    const contributingTables: Array<{
      tableName: string;
      shortLabel: string | null;
      mediumLabel: string | null;
      longLabel: string | null;
      description: string | null;
      pvalueColumn: string | null;
      fdrColumn: string | null;
      rowCount: number;
      bestPvalue: number | null;
      bestFdr: number | null;
      assay: string[] | null;
    }> = [];

    for (const t of tablesWithPvalues) {
      // Subset the breakdown:
      //  - metaAnalysisOnly: keep only the datasets that fed the selected
      //    meta-analysis group (authoritative set from the meta DB, which
      //    already reflects the facet selection + DEG restriction + per-table
      //    meta_analysis:false exclusions).
      //  - otherwise (home): keep datasets matching the restrictor facets.
      if (metaAnalysisOnly) {
        if (metaSourceSet && !metaSourceSet.has(t.table_name)) continue;
      } else if (!facetMatch(t)) {
        continue;
      }

      const linkTableNames = parseLinkTablesForDirection(
        t.link_tables || "",
        direction,
      );
      if (linkTableNames.length === 0) continue;

      // Up/down regulation requires an effect_column on this table.
      if (regulation !== "any" && !t.effect_column) continue;

      const subqueries = linkTableNames.map((lt) => {
        return `SELECT id FROM ${lt} WHERE central_gene_id = ?`;
      });
      const idSubquery =
        subqueries.length === 1 ? subqueries[0] : subqueries.join(" UNION ");
      const params = linkTableNames.map(() => String(centralGeneId));

      try {
        const baseTable = sanitizeIdentifier(t.table_name);

        // Build aggregate query for count, best p-value, best FDR
        const pvalCols = t.pvalue_column
          ? t.pvalue_column.split(",").map((c) => sanitizeIdentifier(c.trim()))
          : [];
        const fdrCols = t.fdr_column
          ? t.fdr_column.split(",").map((c) => sanitizeIdentifier(c.trim()))
          : [];

        const minPvalExpr = pvalCols.length > 0
          ? pvalCols.map((c) => `MIN(${c})`).join(", ")
          : null;
        const minFdrExpr = fdrCols.length > 0
          ? fdrCols.map((c) => `MIN(${c})`).join(", ")
          : null;

        const selectParts = ["COUNT(*) as cnt"];
        if (minPvalExpr) selectParts.push(`${minPvalExpr} as best_pval`);
        if (minFdrExpr) selectParts.push(`${minFdrExpr} as best_fdr`);

        // Sign filter for up/down: bolt onto the WHERE so count/best_*
        // reflect only same-signed rows.
        let signClause = "";
        if (regulation !== "any" && t.effect_column) {
          const effectCol = sanitizeIdentifier(t.effect_column);
          signClause =
            regulation === "up"
              ? ` AND ${effectCol} > 0`
              : ` AND ${effectCol} < 0`;
        }

        const row = db
          .prepare(
            `SELECT ${selectParts.join(", ")} FROM ${baseTable} WHERE id IN (${idSubquery})${signClause}`
          )
          .get(...params) as Record<string, unknown>;

        const cnt = row.cnt as number;
        if (cnt > 0) {
          contributingTables.push({
            tableName: t.table_name,
            shortLabel: t.short_label,
            mediumLabel: t.medium_label,
            longLabel: t.long_label,
            description: t.description,
            pvalueColumn: t.pvalue_column,
            fdrColumn: t.fdr_column,
            rowCount: cnt,
            bestPvalue: minPvalExpr ? (row.best_pval as number | null) : null,
            bestFdr: minFdrExpr ? (row.best_fdr as number | null) : null,
            assay: t.assay
              ? t.assay.split(",").map((s) => s.trim()).filter(Boolean)
              : null,
          });
        }
      } catch {
        // Skip tables that fail
      }
    }

    let geneDescription: string | null = null;
    try {
      const descRow = db
        .prepare(
          "SELECT description FROM gene_descriptions WHERE central_gene_id = ?"
        )
        .get(centralGeneId) as { description: string } | undefined;
      geneDescription = descRow?.description ?? null;
    } catch {
      // gene_descriptions table may not exist yet
    }

    let llmResult: {
      pubmedLinks: string | null;
      summary: string | null;
      status: string;
      searchDate: string;
    } | null = null;
    try {
      const llmRow = db
        .prepare(
          "SELECT pubmed_links, summary, status, search_date FROM llm_gene_results WHERE central_gene_id = ?"
        )
        .get(centralGeneId) as {
        pubmed_links: string | null;
        summary: string | null;
        status: string;
        search_date: string;
      } | undefined;
      if (llmRow) {
        llmResult = {
          pubmedLinks: llmRow.pubmed_links,
          summary: llmRow.summary,
          status: llmRow.status,
          searchDate: llmRow.search_date,
        };
      }
    } catch {
      // llm_gene_results table may not exist yet
    }

    setReadCacheHeaders(res);
    return res.status(200).json({
      centralGeneId,
      combinedPvalues: combined
        ? {
            fisher: combined.fisher_pvalue,
            fisherFdr: combined.fisher_fdr,
            cauchy: combined.cauchy_pvalue,
            cauchyFdr: combined.cauchy_fdr,
            hmp: combined.hmp_pvalue,
            hmpFdr: combined.hmp_fdr,
            numTables: combined.num_tables,
            numPvalues: combined.num_pvalues,
          }
        : null,
      contributingTables,
      geneDescription,
      llmResult,
    });
  } catch (err) {
    console.error("combined-pvalues handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
