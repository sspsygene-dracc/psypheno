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

    const rows = db
      .prepare("SELECT key, label FROM assay_types ORDER BY key ASC")
      .all() as Array<{ key: string; label: string }>;

    const assayTypes: Record<string, string> = {};
    for (const row of rows) {
      assayTypes[row.key] = row.label;
    }

    return res.status(200).json({ assayTypes });
  } catch (err) {
    console.error("assay-types handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
