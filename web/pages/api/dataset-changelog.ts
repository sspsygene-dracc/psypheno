import { NextApiRequest, NextApiResponse } from "next";
import { getDb } from "@/lib/db";

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  try {
    const db = getDb();

    const entries = db
      .prepare(
        `SELECT c.date, c.message, c.table_name,
                d.short_label, d.long_label, d.description,
                d.organism, d.source,
                d.publication_first_author, d.publication_last_author,
                d.publication_year, d.publication_journal, d.publication_doi
         FROM changelog_entries c
         JOIN data_tables d ON c.table_name = d.table_name
         ORDER BY c.date DESC, c.table_name ASC`
      )
      .all() as Array<{
      date: string | null;
      message: string | null;
      table_name: string;
      short_label: string | null;
      long_label: string | null;
      description: string | null;
      organism: string | null;
      source: string | null;
      publication_first_author: string | null;
      publication_last_author: string | null;
      publication_year: number | null;
      publication_journal: string | null;
      publication_doi: string | null;
    }>;

    return res.status(200).json({ entries });
  } catch (err) {
    console.error("dataset-changelog handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
