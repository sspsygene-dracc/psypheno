import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";

const querySchema = z.object({
  tableName: z.string().min(1),
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

  try {
    const db = getDb();

    // Get table metadata
    const metadata = db
      .prepare(
        `SELECT display_columns, description, short_label, long_label,
                links, categories, organism,
                publication_first_author, publication_last_author, publication_year,
                publication_journal, publication_doi, publication_pmid
         FROM data_tables WHERE table_name = ?`
      )
      .get(tableName) as {
        display_columns: string;
        description: string | null;
        short_label: string | null;
        long_label: string | null;
        links: string | null;
        categories: string | null;
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

    // Get all data from the table (preview up to 101 to detect if >100)
    const selectCols = displayCols.join(", ");
    const sql = `SELECT ${selectCols} FROM ${tableName} LIMIT 101`;

    const rows = db.prepare(sql).all() as Record<string, unknown>[];

    // Get total row count
    const totalRowResult = db
      .prepare(`SELECT COUNT(*) as count FROM ${tableName}`)
      .get() as { count: number };
    const totalRows = totalRowResult?.count ?? rows.length;

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

    return res.status(200).json({
      tableName,
      description: metadata.description ?? null,
      shortLabel: metadata.short_label ?? null,
      longLabel: metadata.long_label ?? null,
      organism: metadata.organism ?? null,
      links,
      categories,
      publication: {
        firstAuthor: metadata.publication_first_author,
        lastAuthor: metadata.publication_last_author,
        year: metadata.publication_year,
        journal: metadata.publication_journal,
        doi: metadata.publication_doi,
        pmid: metadata.publication_pmid,
      },
      displayColumns: displayCols,
      rows,
      totalRows,
    });
  } catch (err) {
    console.error("dataset-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}

