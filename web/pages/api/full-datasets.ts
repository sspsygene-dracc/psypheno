import { NextApiRequest, NextApiResponse } from "next";
import { getDb } from "@/lib/db";
import { parseDatasetLinks } from "@/lib/links";

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  try {
    const db = getDb();

    const rows = db
      .prepare(
        `SELECT table_name, short_label, medium_label, long_label, description, gene_columns, gene_species, display_columns, scalar_columns, link_tables,
                links, categories, source, assay, organism,
                publication_first_author, publication_last_author, publication_author_count, publication_authors,
                publication_year, publication_journal, publication_doi, publication_sspsygene_grants
         FROM data_tables
         ORDER BY table_name ASC`
      )
      .all() as Array<{
      table_name: string;
      short_label: string | null;
      medium_label: string | null;
      long_label: string | null;
      description: string | null;
      gene_columns: string;
      gene_species: string;
      display_columns: string;
      scalar_columns: string;
      link_tables: string | null;
      links: string | null;
      categories: string | null;
      source: string | null;
      assay: string | null;
      organism: string | null;
      publication_first_author: string | null;
      publication_last_author: string | null;
      publication_author_count: number | null;
      publication_authors: string | null;
      publication_year: number | null;
      publication_journal: string | null;
      publication_doi: string | null;
      publication_sspsygene_grants: string | null;
    }>;

    const datasets = rows.map((r) => {
      const { publication_authors, publication_sspsygene_grants, links, ...rest } = r;
      let authors: string[] = [];
      if (publication_authors) {
        try {
          const parsed = JSON.parse(publication_authors);
          if (Array.isArray(parsed)) authors = parsed.map(String);
        } catch {
          // ignore malformed JSON
        }
      }
      let grants: string[] = [];
      if (publication_sspsygene_grants) {
        try {
          const parsed = JSON.parse(publication_sspsygene_grants);
          if (Array.isArray(parsed)) grants = parsed.map(String);
        } catch {
          // ignore malformed JSON
        }
      }
      return {
        ...rest,
        links: parseDatasetLinks(links),
        publication_authors: authors,
        publication_sspsygene_grants: grants,
      };
    });

    return res.status(200).json({ datasets });
  } catch (err) {
    console.error("full-datasets handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}

