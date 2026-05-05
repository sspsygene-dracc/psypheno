import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import {
  sanitizeIdentifier,
  validateSortColumn,
  buildOrderByClause,
  buildFilterClause,
  parseSourceColumnsForDirection,
  type ApiSortMode,
} from "@/lib/gene-query";
import { parseDatasetLinks } from "@/lib/links";

const DATASET_PAGE_LIMIT = 10;

const querySchema = z.object({
  tableName: z.string().min(1),
  page: z.coerce.number().min(1).optional(),
  sortBy: z.string().optional(),
  sortMode: z.string().optional(),
  filters: z.string().optional(),
});

function parseFilters(raw: string | undefined): Record<string, string> | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v === "string" && v.trim()) out[k] = v;
    }
    return Object.keys(out).length > 0 ? out : null;
  } catch {
    return null;
  }
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const parse = querySchema.safeParse(req.query);
  if (!parse.success) {
    return res.status(400).json({ error: "Invalid request query" });
  }

  const tableName = sanitizeIdentifier(parse.data.tableName);
  const page = parse.data.page ?? 1;

  try {
    const db = getDb();

    // Get table metadata
    const metadata = db
      .prepare(
        `SELECT display_columns, scalar_columns, description, short_label, medium_label, long_label,
                links, categories, source, assay, field_labels, organism,
                gene_columns, link_tables, pvalue_column, fdr_column,
                publication_first_author, publication_last_author, publication_year,
                publication_journal, publication_doi, publication_pmid
         FROM data_tables WHERE table_name = ?`
      )
      .get(tableName) as {
        display_columns: string;
        scalar_columns: string | null;
        description: string | null;
        short_label: string | null;
        medium_label: string | null;
        long_label: string | null;
        links: string | null;
        categories: string | null;
        source: string | null;
        assay: string | null;
        field_labels: string | null;
        organism: string | null;
        gene_columns: string | null;
        link_tables: string | null;
        pvalue_column: string | null;
        fdr_column: string | null;
        publication_first_author: string | null;
        publication_last_author: string | null;
        publication_year: number | null;
        publication_journal: string | null;
        publication_doi: string | null;
        publication_pmid: string | null;
      } | undefined;

    if (!metadata) {
      return res.status(404).json({ error: "Dataset not found" });
    }

    const displayCols = metadata.display_columns
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map(sanitizeIdentifier);

    if (displayCols.length === 0) {
      return res.status(400).json({ error: "No display columns found" });
    }

    const selectCols = displayCols.join(", ");

    const scalarCols = new Set(
      (metadata.scalar_columns || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
    );

    // Build WHERE clause from per-column filters (if any)
    const filterMap = parseFilters(parse.data.filters);
    const filterSpec = buildFilterClause({
      filters: filterMap,
      displayColumns: displayCols,
      scalarColumns: scalarCols,
    });
    const whereClause = filterSpec.clause ? `WHERE ${filterSpec.clause}` : "";
    const filterParams = filterSpec.params;

    // Get total row count (after filtering)
    const totalRowResult = db
      .prepare(`SELECT COUNT(*) as count FROM ${tableName} ${whereClause}`)
      .get(...filterParams) as { count: number };
    const totalRows = totalRowResult?.count ?? 0;
    const totalPages = Math.max(1, Math.ceil(totalRows / DATASET_PAGE_LIMIT));
    const effectivePage = Math.min(page, totalPages);
    const offset = (effectivePage - 1) * DATASET_PAGE_LIMIT;

    // Build ORDER BY clause if sort params provided
    let orderByClause = "";
    if (parse.data.sortBy && parse.data.sortMode) {
      const validModes = new Set(["asc", "desc", "asc_abs", "desc_abs"]);
      if (validModes.has(parse.data.sortMode)) {
        const validCol = validateSortColumn(parse.data.sortBy, displayCols);
        if (validCol) {
          let mode = parse.data.sortMode as ApiSortMode;
          const isAbsMode = mode === "asc_abs" || mode === "desc_abs";
          if (isAbsMode && !scalarCols.has(validCol)) {
            mode = mode === "asc_abs" ? "asc" : "desc";
          }
          orderByClause = buildOrderByClause({ column: validCol, mode });
        }
      }
    }

    const sql = `SELECT ${selectCols} FROM ${tableName} ${whereClause} ${orderByClause} LIMIT ${DATASET_PAGE_LIMIT} OFFSET ${offset}`;
    const rows = db.prepare(sql).all(...filterParams) as Record<string, unknown>[];

    const links = parseDatasetLinks(metadata.links);
    const categories =
      metadata.categories
        ?.split(",")
        .map((s) => s.trim())
        .filter(Boolean) ?? [];

    const assay =
      metadata.assay
        ?.split(",")
        .map((s) => s.trim())
        .filter(Boolean) ?? [];

    let fieldLabels: Record<string, string> | null = null;
    if (metadata.field_labels) {
      try {
        fieldLabels = JSON.parse(metadata.field_labels);
      } catch {
        fieldLabels = null;
      }
    }

    return res.status(200).json({
      tableName,
      page: effectivePage,
      totalPages,
      description: metadata.description ?? null,
      shortLabel: metadata.short_label ?? null,
      mediumLabel: metadata.medium_label ?? null,
      longLabel: metadata.long_label ?? null,
      organism: metadata.organism ?? null,
      source: metadata.source ?? null,
      links,
      categories,
      assay,
      fieldLabels,
      publication: {
        firstAuthor: metadata.publication_first_author,
        lastAuthor: metadata.publication_last_author,
        year: metadata.publication_year,
        journal: metadata.publication_journal,
        doi: metadata.publication_doi,
        pmid: metadata.publication_pmid,
      },
      displayColumns: displayCols,
      scalarColumns: Array.from(scalarCols),
      geneColumns: (metadata.gene_columns || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      perturbedGeneColumns: parseSourceColumnsForDirection(
        metadata.link_tables || "",
        "perturbed",
      ),
      pvalueColumn: metadata.pvalue_column ?? null,
      fdrColumn: metadata.fdr_column ?? null,
      rows,
      totalRows,
    });
  } catch (err) {
    console.error("dataset-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}

