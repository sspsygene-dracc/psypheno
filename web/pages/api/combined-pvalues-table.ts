import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { sanitizeIdentifier } from "@/lib/gene-query";

const VALID_SORT_COLUMNS: Record<string, string> = {
  fisher_pvalue: "fisher_pvalue",
  stouffer_pvalue: "stouffer_pvalue",
  cauchy_pvalue: "cauchy_pvalue",
  hmp_pvalue: "hmp_pvalue",
  num_tables: "num_tables",
  num_pvalues: "num_pvalues",
  human_symbol: "human_symbol",
  llm_search_date: "search_date",
};

const VALID_FLAGS = [
  "heat_shock",
  "mitochondrial_rna",
  "no_hgnc",
  "non_coding",
  "pseudogene",
  "ribosomal",
  "ubiquitin",
] as const;

const bodySchema = z.object({
  page: z.number().int().min(1).default(1),
  pageSize: z.number().int().min(1).max(100).default(25),
  sortBy: z.string().default("fisher_pvalue"),
  sortDir: z.enum(["asc", "desc"]).default("asc"),
  hideFlags: z.array(z.enum(VALID_FLAGS)).default([]),
});

/** Check whether a table exists in the database. */
function tableExists(db: ReturnType<typeof getDb>, name: string): boolean {
  const row = db
    .prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
    )
    .get(name) as { name: string } | undefined;
  return !!row;
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

  const { page, pageSize, sortBy, sortDir, hideFlags } = parse.data;

  if (!VALID_SORT_COLUMNS[sortBy]) {
    return res.status(400).json({ error: "Invalid sortBy column" });
  }

  try {
    const db = getDb();
    const offset = (page - 1) * pageSize;
    const hasLlm = tableExists(db, "llm_gene_results");

    // Sort column may be on cp, cg, or lr table
    // If LLM table doesn't exist, fall back to default sort
    const effectiveSortBy = (sortBy.startsWith("llm_") && !hasLlm) ? "fisher_pvalue" : sortBy;
    const effectiveSortCol = VALID_SORT_COLUMNS[effectiveSortBy] ?? "fisher_pvalue";
    const sortTable = effectiveSortBy === "human_symbol"
      ? "cg"
      : effectiveSortBy.startsWith("llm_")
        ? "lr"
        : "cp";
    const dir = sortDir === "desc" ? "DESC" : "ASC";
    const nullsLast = sortDir === "asc" ? "NULLS LAST" : "NULLS FIRST";

    // Build WHERE clause to exclude genes with hidden flags
    let flagWhere = "";
    const flagParams: string[] = [];
    if (hideFlags.length > 0) {
      const conditions = hideFlags.map(() => "cp.gene_flags LIKE ?");
      flagWhere = `WHERE (cp.gene_flags IS NULL OR NOT (${conditions.join(" OR ")}))`;
      for (const flag of hideFlags) {
        flagParams.push(`%${flag}%`);
      }
    }

    const llmSelect = hasLlm
      ? `, lr.pubmed_links AS llm_pubmed_links,
           lr.summary AS llm_summary,
           lr.search_date AS llm_search_date,
           lr.status AS llm_status`
      : `, NULL AS llm_pubmed_links,
           NULL AS llm_summary,
           NULL AS llm_search_date,
           NULL AS llm_status`;

    const llmJoin = hasLlm
      ? "LEFT JOIN llm_gene_results lr ON lr.central_gene_id = cp.central_gene_id"
      : "";

    const rows = db
      .prepare(
        `SELECT cg.human_symbol, cp.fisher_pvalue,
                cp.stouffer_pvalue,
                cp.cauchy_pvalue,
                cp.hmp_pvalue,
                cp.num_tables, cp.num_pvalues,
                cp.gene_flags
                ${llmSelect}
         FROM gene_combined_pvalues cp
         JOIN central_gene cg ON cg.id = cp.central_gene_id
         ${llmJoin}
         ${flagWhere}
         ORDER BY ${sortTable}.${sanitizeIdentifier(effectiveSortCol)} ${dir} ${nullsLast}
         LIMIT ? OFFSET ?`
      )
      .all(...flagParams, pageSize, offset) as Array<Record<string, unknown>>;

    const countResult = db
      .prepare(
        `SELECT COUNT(*) as cnt FROM gene_combined_pvalues cp ${flagWhere}`
      )
      .get(...flagParams) as { cnt: number };

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
