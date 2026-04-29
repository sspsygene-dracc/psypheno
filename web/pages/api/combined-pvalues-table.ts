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
  "lncrna",
  "mitochondrial_rna",
  "nimh_priority",
  "no_hgnc",
  "non_coding",
  "pseudogene",
  "ribosomal",
  "transcription_factor",
  "ubiquitin",
] as const;

/** Positive "show" flags — used for the "Show union of" filter. */
const SHOW_FLAGS = [
  "nimh_priority",
  "transcription_factor",
  "lncrna",
] as const;

const bodySchema = z.object({
  page: z.number().int().min(1).default(1),
  pageSize: z.number().int().min(1).max(100).default(25),
  method: z.enum(VALID_METHODS).default("fisher"),
  hideFlags: z.array(z.enum(VALID_FLAGS)).default([]),
  showFlags: z
    .array(z.enum(VALID_FLAGS))
    .default([...SHOW_FLAGS, "__other__" as any]),
  showOther: z.boolean().default(true),
  assayFilter: z.string().regex(/^[a-z0-9_]+$/).nullable().default(null),
  diseaseFilter: z.string().regex(/^[a-z0-9_]+$/).nullable().default(null),
  organismFilter: z.string().regex(/^[a-z0-9_]+$/).nullable().default(null),
  geneSearch: z.string().max(50).regex(/^[A-Za-z0-9._-]*$/).default(""),
  direction: z.enum(["target", "perturbed"]).default("target"),
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

  const { page, pageSize, method, hideFlags, showFlags, showOther, assayFilter, diseaseFilter, organismFilter, geneSearch, direction } =
    parse.data;
  const methodCol = METHOD_COLUMNS[method];

  try {
    const db = getDb();
    const offset = (page - 1) * pageSize;
    const hasLlm = tableExists(db, "llm_gene_results");
    const hasDesc = tableExists(db, "gene_descriptions");

    // Determine which combined p-values table to query. Every group is
    // direction-aware ("target" or "perturbed"); filter combinations look up
    // the matching table via combined_pvalue_groups.
    let cpTable = `gene_combined_pvalues_${direction}`;
    let noTable = false;
    let numSourceTables = 0;
    if (assayFilter || diseaseFilter || organismFilter) {
      const hasGroups = tableExists(db, "combined_pvalue_groups");
      if (hasGroups) {
        const group = db
          .prepare(
            `SELECT table_name, num_source_tables FROM combined_pvalue_groups
             WHERE assay_filter IS ? AND disease_filter IS ? AND organism_filter IS ? AND direction = ?`
          )
          .get(
            assayFilter ?? null,
            diseaseFilter ?? null,
            organismFilter ?? null,
            direction,
          ) as
          | { table_name: string | null; num_source_tables: number }
          | undefined;
        if (group && group.table_name) {
          cpTable = group.table_name;
          numSourceTables = group.num_source_tables;
        } else if (group) {
          // Group exists but no table (< 2 source tables)
          noTable = true;
          numSourceTables = group.num_source_tables;
        } else {
          noTable = true;
        }
      } else {
        noTable = true;
      }
    }

    if (noTable) {
      return res.status(200).json({
        rows: [],
        totalRows: 0,
        page,
        pageSize,
        method,
        noTable: true,
        numSourceTables,
        message:
          numSourceTables === 1
            ? "Only one dataset matches this combination — no meta-analysis needed. Browse individual dataset results on the significant rows page."
            : "No datasets match this combination.",
      });
    }

    // Build WHERE conditions
    const conditions: string[] = [];
    const flagParams: string[] = [];

    // 1. Exclude genes with hidden flags
    if (hideFlags.length > 0) {
      const hideConds = hideFlags.map(() => "cp.gene_flags LIKE ?");
      conditions.push(
        `(cp.gene_flags IS NULL OR NOT (${hideConds.join(" OR ")}))`
      );
      for (const flag of hideFlags) {
        flagParams.push(`%${flag}%`);
      }
    }

    // 2. Show-flag inclusion filter (union logic)
    // Only active show flags from SHOW_FLAGS are considered.
    const activeShowFlags = showFlags.filter((f) =>
      (SHOW_FLAGS as readonly string[]).includes(f)
    );
    const allShowFlagsActive =
      activeShowFlags.length === SHOW_FLAGS.length && showOther;

    if (!allShowFlagsActive) {
      // Build: gene matches if it has ANY of the active show flags,
      // OR (if showOther) it has NONE of the show flags.
      const parts: string[] = [];
      for (const flag of activeShowFlags) {
        parts.push("cp.gene_flags LIKE ?");
        flagParams.push(`%${flag}%`);
      }
      if (showOther) {
        // Gene has none of the show-category flags
        const noneConditions = SHOW_FLAGS.map(
          () => "(cp.gene_flags IS NULL OR cp.gene_flags NOT LIKE ?)"
        );
        parts.push(`(${noneConditions.join(" AND ")})`);
        for (const flag of SHOW_FLAGS) {
          flagParams.push(`%${flag}%`);
        }
      }
      if (parts.length > 0) {
        conditions.push(`(${parts.join(" OR ")})`);
      } else {
        // Nothing selected — show nothing
        conditions.push("0");
      }
    }

    const flagWhere =
      conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

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

    // Two-CTE approach: ranks are computed over the flag-filtered set,
    // then gene name search is applied as an outer filter so ranks stay stable.
    const geneSearchWhere = geneSearch
      ? "WHERE r.human_symbol LIKE ?"
      : "";
    const geneSearchParams = geneSearch ? [geneSearch + "%"] : [];

    const rows = db
      .prepare(
        `WITH filtered AS (
           SELECT cp.central_gene_id,
                  cp.${methodCol} AS method_pvalue,
                  cp.num_tables, cp.num_pvalues, cp.gene_flags
           FROM ${cpTable} cp
           ${flagWhere}
         ),
         ranked AS (
           SELECT ROW_NUMBER() OVER (ORDER BY f.method_pvalue ASC NULLS LAST) AS rank,
                  cg.human_symbol, f.central_gene_id, f.method_pvalue,
                  f.num_tables, f.num_pvalues, f.gene_flags
           FROM filtered f
           JOIN central_gene cg ON cg.id = f.central_gene_id
         )
         SELECT r.rank, r.central_gene_id, r.human_symbol, r.method_pvalue,
                r.num_tables, r.num_pvalues, r.gene_flags
                ${llmSelect}
                ${descSelect}
         FROM ranked r
         ${hasLlm ? "LEFT JOIN llm_gene_results lr ON lr.central_gene_id = r.central_gene_id" : ""}
         ${hasDesc ? "LEFT JOIN gene_descriptions gd ON gd.central_gene_id = r.central_gene_id" : ""}
         ${geneSearchWhere}
         ORDER BY r.method_pvalue ASC NULLS LAST
         LIMIT ? OFFSET ?`
      )
      .all(...flagParams, ...geneSearchParams, pageSize, offset) as Array<Record<string, unknown>>;

    const countResult = geneSearch
      ? db
          .prepare(
            `WITH filtered AS (
               SELECT cp.central_gene_id
               FROM ${cpTable} cp
               ${flagWhere}
             )
             SELECT COUNT(*) as cnt
             FROM filtered f
             JOIN central_gene cg ON cg.id = f.central_gene_id
             WHERE cg.human_symbol LIKE ?`
          )
          .get(...flagParams, geneSearch + "%") as { cnt: number }
      : db
          .prepare(
            `SELECT COUNT(*) as cnt FROM ${cpTable} cp ${flagWhere}`
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
