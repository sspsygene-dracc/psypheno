import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { sanitizeIdentifier } from "@/lib/gene-query";

const VALID_SORT_COLUMNS: Record<string, string> = {
  fisher_pvalue: "fisher_pvalue",
  fisher_fdr: "fisher_fdr",
  stouffer_pvalue: "stouffer_pvalue",
  stouffer_fdr: "stouffer_fdr",
  cauchy_pvalue: "cauchy_pvalue",
  cauchy_fdr: "cauchy_fdr",
  hmp_pvalue: "hmp_pvalue",
  hmp_fdr: "hmp_fdr",
  num_tables: "num_tables",
  num_pvalues: "num_pvalues",
  human_symbol: "human_symbol",
};

const bodySchema = z.object({
  page: z.number().int().min(1).default(1),
  pageSize: z.number().int().min(1).max(100).default(25),
  sortBy: z.string().default("fisher_pvalue"),
  sortDir: z.enum(["asc", "desc"]).default("asc"),
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

  const { page, pageSize, sortBy, sortDir } = parse.data;

  const sortColumn = VALID_SORT_COLUMNS[sortBy];
  if (!sortColumn) {
    return res.status(400).json({ error: "Invalid sortBy column" });
  }

  try {
    const db = getDb();
    const offset = (page - 1) * pageSize;

    // Sort column may be on cp or cg table
    const sortTable = sortBy === "human_symbol" ? "cg" : "cp";
    const dir = sortDir === "desc" ? "DESC" : "ASC";
    const nullsLast = sortDir === "asc" ? "NULLS LAST" : "NULLS FIRST";

    const rows = db
      .prepare(
        `SELECT cg.human_symbol, cp.fisher_pvalue, cp.fisher_fdr,
                cp.stouffer_pvalue, cp.stouffer_fdr,
                cp.cauchy_pvalue, cp.cauchy_fdr,
                cp.hmp_pvalue, cp.hmp_fdr,
                cp.num_tables, cp.num_pvalues
         FROM gene_combined_pvalues cp
         JOIN central_gene cg ON cg.id = cp.central_gene_id
         ORDER BY ${sortTable}.${sanitizeIdentifier(sortColumn)} ${dir} ${nullsLast}
         LIMIT ? OFFSET ?`
      )
      .all(pageSize, offset) as Array<Record<string, unknown>>;

    const countResult = db
      .prepare("SELECT COUNT(*) as cnt FROM gene_combined_pvalues")
      .get() as { cnt: number };

    return res.status(200).json({
      rows,
      totalRows: countResult.cnt,
      page,
      pageSize,
    });
  } catch (err) {
    console.error("combined-pvalues-table handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
