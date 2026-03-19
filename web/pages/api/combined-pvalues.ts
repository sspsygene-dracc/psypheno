import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { sanitizeIdentifier, parseNonPerturbedLinkTables } from "@/lib/gene-query";

const bodySchema = z.object({
  centralGeneId: z.number().min(0),
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

  const centralGeneId = parse.data.centralGeneId;

  try {
    const db = getDb();

    // Fetch pre-computed combined p-values
    const combined = db
      .prepare(
        `SELECT fisher_pvalue, fisher_fdr, stouffer_pvalue, stouffer_fdr,
                cauchy_pvalue, cauchy_fdr, hmp_pvalue, hmp_fdr,
                num_tables, num_pvalues
         FROM gene_combined_pvalues WHERE central_gene_id = ?`
      )
      .get(centralGeneId) as {
        fisher_pvalue: number | null;
        fisher_fdr: number | null;
        stouffer_pvalue: number | null;
        stouffer_fdr: number | null;
        cauchy_pvalue: number | null;
        cauchy_fdr: number | null;
        hmp_pvalue: number | null;
        hmp_fdr: number | null;
        num_tables: number;
        num_pvalues: number;
      } | undefined;

    // Fetch all tables that have pvalue/fdr columns
    const tablesWithPvalues = db
      .prepare(
        `SELECT table_name, short_label, medium_label, long_label, description, pvalue_column, fdr_column,
                link_tables, field_labels, assay
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
      }>;

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
      const linkTableNames = parseNonPerturbedLinkTables(t.link_tables || "");
      if (linkTableNames.length === 0) continue;

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

        const row = db
          .prepare(
            `SELECT ${selectParts.join(", ")} FROM ${baseTable} WHERE id IN (${idSubquery})`
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

    return res.status(200).json({
      centralGeneId,
      combinedPvalues: combined
        ? {
            fisher: combined.fisher_pvalue,
            fisherFdr: combined.fisher_fdr,
            stouffer: combined.stouffer_pvalue,
            stoufferFdr: combined.stouffer_fdr,
            cauchy: combined.cauchy_pvalue,
            cauchyFdr: combined.cauchy_fdr,
            hmp: combined.hmp_pvalue,
            hmpFdr: combined.hmp_fdr,
            numTables: combined.num_tables,
            numPvalues: combined.num_pvalues,
          }
        : null,
      contributingTables,
    });
  } catch (err) {
    console.error("combined-pvalues handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
