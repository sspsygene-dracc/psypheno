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
        `SELECT table_name, short_label, long_label, description,
                date_added, organism, source,
                publication_first_author, publication_last_author,
                publication_year, publication_journal, publication_doi
         FROM data_tables
         ORDER BY date_added DESC, table_name ASC`
      )
      .all() as Array<{
      table_name: string;
      short_label: string | null;
      long_label: string | null;
      description: string | null;
      date_added: string | null;
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
