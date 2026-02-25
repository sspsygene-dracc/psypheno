import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";

const DATASET_PAGE_LIMIT = 25;

const querySchema = z.object({
  tableName: z.string().min(1),
  page: z.coerce.number().min(1).optional(),
});

function sanitizeIdentifier(id: string): string {
  // Allow only alphanumeric and underscore to avoid SQL injection via identifiers
  if (!/^\w+$/.test(id)) throw new Error(`Invalid identifier: ${id}`);
  return id;
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
        `SELECT display_columns, scalar_columns, description, short_label, long_label,
                links, categories, source, assay, field_labels, organism,
                publication_first_author, publication_last_author, publication_year,
                publication_journal, publication_doi, publication_pmid
         FROM data_tables WHERE table_name = ?`
      )
      .get(tableName) as {
        display_columns: string;
        scalar_columns: string | null;
        description: string | null;
        short_label: string | null;
        long_label: string | null;
        links: string | null;
        categories: string | null;
        source: string | null;
        assay: string | null;
        field_labels: string | null;
        organism: string | null;
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

    // Get total row count
    const totalRowResult = db
      .prepare(`SELECT COUNT(*) as count FROM ${tableName}`)
      .get() as { count: number };
    const totalRows = totalRowResult?.count ?? 0;
    const totalPages = Math.max(1, Math.ceil(totalRows / DATASET_PAGE_LIMIT));
    const effectivePage = Math.min(page, totalPages);
    const offset = (effectivePage - 1) * DATASET_PAGE_LIMIT;

    const sql = `SELECT ${selectCols} FROM ${tableName} LIMIT ${DATASET_PAGE_LIMIT} OFFSET ${offset}`;
    const rows = db.prepare(sql).all() as Record<string, unknown>[];

    const links =
      metadata.links
        ?.split(",")
        .map((s) => s.trim())
        .filter(Boolean) ?? [];
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
      scalarColumns: (metadata.scalar_columns || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      rows,
      totalRows,
    });
  } catch (err) {
    console.error("dataset-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}

