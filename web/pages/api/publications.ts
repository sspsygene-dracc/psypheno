import { NextApiRequest, NextApiResponse } from "next";
import { getDb } from "@/lib/db";

export type PublicationTableEntry = {
  tableName: string;
  label: string;
  organism: string | null;
  links: string[];
};

export type PublicationEntry = {
  doi: string;
  pmid: string | null;
  year: number | null;
  journal: string | null;
  firstAuthor: string | null;
  lastAuthor: string | null;
  authorCount: number | null;
  authors: string[];
  organisms: string[];
  tables: PublicationTableEntry[];
};

export default async function handler(
  _req: NextApiRequest,
  res: NextApiResponse,
) {
  try {
    const db = getDb();

    const rows = db
      .prepare(
        `SELECT
           table_name, medium_label, organism, links,
           publication_doi, publication_pmid, publication_year, publication_journal,
           publication_first_author, publication_last_author, publication_author_count,
           publication_authors
         FROM data_tables
         WHERE publication_doi IS NOT NULL
         ORDER BY publication_year DESC, publication_first_author ASC, table_name ASC`,
      )
      .all() as Array<{
      table_name: string;
      medium_label: string | null;
      organism: string | null;
      links: string | null;
      publication_doi: string;
      publication_pmid: string | null;
      publication_year: number | null;
      publication_journal: string | null;
      publication_first_author: string | null;
      publication_last_author: string | null;
      publication_author_count: number | null;
      publication_authors: string | null;
    }>;

    const byDoi = new Map<string, PublicationEntry>();

    for (const r of rows) {
      let entry = byDoi.get(r.publication_doi);
      if (!entry) {
        let parsedAuthors: string[] = [];
        if (r.publication_authors) {
          try {
            const v = JSON.parse(r.publication_authors);
            if (Array.isArray(v))
              parsedAuthors = v.filter((x): x is string => typeof x === "string");
          } catch {
            // leave empty
          }
        }
        entry = {
          doi: r.publication_doi,
          pmid: r.publication_pmid,
          year: r.publication_year,
          journal: r.publication_journal,
          firstAuthor: r.publication_first_author,
          lastAuthor: r.publication_last_author,
          authorCount: r.publication_author_count,
          authors: parsedAuthors,
          organisms: [],
          tables: [],
        };
        byDoi.set(r.publication_doi, entry);
      }
      const tableLinks = (r.links || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      entry.tables.push({
        tableName: r.table_name,
        label: r.medium_label || r.table_name,
        organism: r.organism,
        links: tableLinks,
      });
      if (r.organism && !entry.organisms.includes(r.organism)) {
        entry.organisms.push(r.organism);
      }
    }

    return res.status(200).json({ publications: Array.from(byDoi.values()) });
  } catch (err) {
    console.error("publications handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
