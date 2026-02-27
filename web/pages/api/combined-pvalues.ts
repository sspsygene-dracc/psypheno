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
        `SELECT table_name, short_label, description, pvalue_column, fdr_column,
                link_tables, field_labels
         FROM data_tables
         WHERE pvalue_column IS NOT NULL OR fdr_column IS NOT NULL
         ORDER BY id ASC`
      )
      .all() as Array<{
        table_name: string;
        short_label: string | null;
        description: string | null;
        pvalue_column: string | null;
        fdr_column: string | null;
        link_tables: string | null;
        field_labels: string | null;
      }>;

    // For each table, count how many rows this gene has
    const contributingTables: Array<{
      tableName: string;
      shortLabel: string | null;
      description: string | null;
      pvalueColumn: string | null;
      fdrColumn: string | null;
      rowCount: number;
    }> = [];

    for (const t of tablesWithPvalues) {
      const linkTableNames = parseNonPerturbedLinkTables(t.link_tables || "");
      if (linkTableNames.length === 0) continue;

      // Count rows for this gene in this table
      const subqueries = linkTableNames.map((lt) => {
        return `SELECT id FROM ${lt} WHERE central_gene_id = ?`;
      });
      const idSubquery =
        subqueries.length === 1 ? subqueries[0] : subqueries.join(" UNION ");
      const params = linkTableNames.map(() => String(centralGeneId));

      try {
        const baseTable = sanitizeIdentifier(t.table_name);
        const countResult = db
          .prepare(
            `SELECT COUNT(*) as cnt FROM ${baseTable} WHERE id IN (${idSubquery})`
          )
          .get(...params) as { cnt: number };

        if (countResult.cnt > 0) {
          contributingTables.push({
            tableName: t.table_name,
            shortLabel: t.short_label,
            description: t.description,
            pvalueColumn: t.pvalue_column,
            fdrColumn: t.fdr_column,
            rowCount: countResult.cnt,
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
