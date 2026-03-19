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
        `SELECT table_name, short_label, medium_label, long_label, pvalue_column, fdr_column, assay, disease
         FROM data_tables
         WHERE pvalue_column IS NOT NULL OR fdr_column IS NOT NULL
         ORDER BY id ASC`
      )
      .all() as Array<{
        table_name: string;
        short_label: string | null;
        medium_label: string | null;
        long_label: string | null;
        pvalue_column: string | null;
        fdr_column: string | null;
        assay: string | null;
        disease: string | null;
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

    // Fetch disease type labels
    let diseaseTypeLabels: Record<string, string> = {};
    try {
      const diseaseRows = db
        .prepare("SELECT key, label FROM disease_types")
        .all() as Array<{ key: string; label: string }>;
      diseaseTypeLabels = Object.fromEntries(
        diseaseRows.map((r) => [r.key, r.label])
      );
    } catch {
      // disease_types table may not exist
    }

    // Fetch available filter combinations from combined_pvalue_groups
    let combinedPvalueGroups: Array<{
      assayFilter: string | null;
      diseaseFilter: string | null;
      tableName: string | null;
      numSourceTables: number;
    }> = [];
    try {
      const rawGroups = db
        .prepare("SELECT assay_filter, disease_filter, table_name, num_source_tables FROM combined_pvalue_groups")
        .all() as Array<{
          assay_filter: string | null;
          disease_filter: string | null;
          table_name: string | null;
          num_source_tables: number;
        }>;
      combinedPvalueGroups = rawGroups.map((g) => ({
        assayFilter: g.assay_filter,
        diseaseFilter: g.disease_filter,
        tableName: g.table_name,
        numSourceTables: g.num_source_tables,
      }));
    } catch {
      // table may not exist
    }

    return res.status(200).json({
      tables: rows.map((r) => ({
        tableName: r.table_name,
        shortLabel: r.short_label,
        mediumLabel: r.medium_label,
        longLabel: r.long_label,
        pvalueColumn: r.pvalue_column,
        fdrColumn: r.fdr_column,
        assay: r.assay ? r.assay.split(",").map((s) => s.trim()).filter(Boolean) : null,
        disease: r.disease ? r.disease.split(",").map((s) => s.trim()).filter(Boolean) : null,
      })),
      assayTypeLabels,
      diseaseTypeLabels,
      combinedPvalueGroups,
    });
  } catch (err) {
    console.error("dataset-tables-with-pvalues handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
