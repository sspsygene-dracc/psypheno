import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { sanitizeIdentifier, parseDisplayColumns, buildGeneQuery, queryFirstPage } from "@/lib/gene-query";

const bodySchema = z.object({
  centralGeneId: z.number().min(0),
  direction: z.enum(["target", "perturbed"]).optional(),
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
  const direction = parse.data.direction ?? "target";

  try {
    const db = getDb();

    const tables = db
      .prepare(
        `SELECT table_name, short_label, medium_label, long_label, description, source, assay, field_labels, gene_columns, display_columns, scalar_columns, link_tables, pvalue_column, fdr_column, publication_first_author, publication_last_author, publication_author_count, publication_year, publication_journal, publication_doi FROM data_tables ORDER BY id ASC`
      )
      .all() as Array<{
        table_name: string;
        short_label: string | null;
        medium_label: string | null;
        long_label: string | null;
        description: string | null;
        source: string | null;
        assay: string | null;
        field_labels: string | null;
        gene_columns: string;
        display_columns: string;
        scalar_columns: string | null;
        link_tables: string | null;
        pvalue_column: string | null;
        fdr_column: string | null;
        publication_first_author: string | null;
        publication_last_author: string | null;
        publication_author_count: number | null;
        publication_year: number | null;
        publication_journal: string | null;
        publication_doi: string | null;
      }>;

    const results: Array<{
      tableName: string;
      shortLabel: string | null;
      mediumLabel: string | null;
      longLabel: string | null;
      description: string | null;
      source: string | null;
      assay: string[];
      fieldLabels: Record<string, string> | null;
      displayColumns: string[];
      scalarColumns: string[];
      geneColumns: string[];
      pvalueColumn: string | null;
      fdrColumn: string | null;
      publicationFirstAuthor: string | null;
      publicationLastAuthor: string | null;
      publicationAuthorCount: number | null;
      publicationYear: number | null;
      publicationJournal: string | null;
      publicationDoi: string | null;
      rows: Record<string, unknown>[];
      totalRows: number;
    }> = [];

    for (const t of tables) {
      const baseTable = sanitizeIdentifier(t.table_name);
      const displayCols = parseDisplayColumns(t.display_columns);
      if (displayCols.length === 0) continue;

      const query = buildGeneQuery({
        baseTable,
        displayCols,
        linkTablesRaw: t.link_tables || "",
        centralGeneId,
        direction,
      });
      if (!query) continue;

      try {
        const result = queryFirstPage(db, query.selectCols, query.fromAndWhere, query.params);
        if (!result) continue;

        let fieldLabels: Record<string, string> | null = null;
        if (t.field_labels) {
          try {
            fieldLabels = JSON.parse(t.field_labels);
          } catch {
            fieldLabels = null;
          }
        }
        const assay = (t.assay || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
        results.push({
          tableName: t.table_name,
          shortLabel: t.short_label ?? null,
          mediumLabel: t.medium_label ?? null,
          longLabel: t.long_label ?? null,
          description: t.description ?? null,
          source: t.source ?? null,
          assay,
          fieldLabels,
          displayColumns: displayCols,
          scalarColumns: (t.scalar_columns || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          geneColumns: (t.gene_columns || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          pvalueColumn: t.pvalue_column ?? null,
          fdrColumn: t.fdr_column ?? null,
          publicationFirstAuthor: t.publication_first_author ?? null,
          publicationLastAuthor: t.publication_last_author ?? null,
          publicationAuthorCount: t.publication_author_count ?? null,
          publicationYear: t.publication_year ?? null,
          publicationJournal: t.publication_journal ?? null,
          publicationDoi: t.publication_doi ?? null,
          rows: result.rows,
          totalRows: result.totalRows,
        });
      } catch (innerErr) {
        // Skip tables that fail (e.g., column missing) to keep response robust
        // eslint-disable-next-line no-console
        console.error(`Query failed for table ${baseTable}`, innerErr);
      }
    }

    // Fetch gene description (graceful if table missing)
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

    // Fetch LLM search results (graceful if table missing)
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

    return res
      .status(200)
      .json({ centralGeneId, results, geneDescription, llmResult });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("gene-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
