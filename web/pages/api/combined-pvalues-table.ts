import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";

const VALID_METHODS = ["fisher", "stouffer", "cauchy", "hmp"] as const;

const METHOD_COLUMNS: Record<string, string> = {
  fisher: "fisher_pvalue",
  stouffer: "stouffer_pvalue",
  cauchy: "cauchy_pvalue",
  hmp: "hmp_pvalue",
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
  method: z.enum(VALID_METHODS).default("fisher"),
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

  const { page, pageSize, method, hideFlags } = parse.data;
  const methodCol = METHOD_COLUMNS[method];

  try {
    const db = getDb();
    const offset = (page - 1) * pageSize;
    const hasLlm = tableExists(db, "llm_gene_results");
    const hasDesc = tableExists(db, "gene_descriptions");

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

    const descSelect = hasDesc
      ? `, gd.description AS gene_description`
      : `, NULL AS gene_description`;

    const llmJoin = hasLlm
      ? "LEFT JOIN llm_gene_results lr ON lr.central_gene_id = f.central_gene_id"
      : "";

    const descJoin = hasDesc
      ? "LEFT JOIN gene_descriptions gd ON gd.central_gene_id = f.central_gene_id"
      : "";

    // CTE computes rank over the filtered set, then we join extra data
    const rows = db
      .prepare(
        `WITH filtered AS (
           SELECT cp.central_gene_id,
                  cp.${methodCol} AS method_pvalue,
                  cp.num_tables, cp.num_pvalues, cp.gene_flags
           FROM gene_combined_pvalues cp
           ${flagWhere}
         )
         SELECT ROW_NUMBER() OVER (ORDER BY f.method_pvalue ASC NULLS LAST) AS rank,
                cg.human_symbol, f.method_pvalue,
                f.num_tables, f.num_pvalues, f.gene_flags
                ${llmSelect}
                ${descSelect}
         FROM filtered f
         JOIN central_gene cg ON cg.id = f.central_gene_id
         ${llmJoin}
         ${descJoin}
         ORDER BY f.method_pvalue ASC NULLS LAST
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
      method,
    });
  } catch (err) {
    console.error("combined-pvalues-table handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
