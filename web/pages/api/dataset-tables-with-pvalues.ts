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
      .prepare(
        `SELECT table_name, short_label, pvalue_column, fdr_column, assay
         FROM data_tables
         WHERE pvalue_column IS NOT NULL OR fdr_column IS NOT NULL
         ORDER BY id ASC`
      )
      .all() as Array<{
        table_name: string;
        short_label: string | null;
        pvalue_column: string | null;
        fdr_column: string | null;
        assay: string | null;
      }>;

    // Also fetch assay type labels
    let assayTypeLabels: Record<string, string> = {};
    try {
      const assayRows = db
        .prepare("SELECT key, label FROM assay_types")
        .all() as Array<{ key: string; label: string }>;
      assayTypeLabels = Object.fromEntries(
        assayRows.map((r) => [r.key, r.label])
      );
    } catch {
      // assay_types table may not exist
    }

    return res.status(200).json({
      tables: rows.map((r) => ({
        tableName: r.table_name,
        shortLabel: r.short_label,
        pvalueColumn: r.pvalue_column,
        fdrColumn: r.fdr_column,
        assay: r.assay ? r.assay.split(",").map((s) => s.trim()).filter(Boolean) : null,
      })),
      assayTypeLabels,
    });
  } catch (err) {
    console.error("dataset-tables-with-pvalues handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
