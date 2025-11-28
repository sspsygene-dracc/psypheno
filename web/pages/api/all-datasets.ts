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

    const datasets = db
      .prepare(
        `SELECT table_name, short_label, long_label, description, gene_columns, gene_species, display_columns, scalar_columns, link_tables 
         FROM data_tables 
         ORDER BY table_name ASC`
      )
      .all() as Array<{
      table_name: string;
      short_label: string | null;
      long_label: string | null;
      description: string | null;
      gene_columns: string;
      gene_species: string;
      display_columns: string;
      scalar_columns: string;
      link_tables: string | null;
    }>;

    return res.status(200).json({ datasets });
  } catch (err) {
    console.error("all-datasets handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}

