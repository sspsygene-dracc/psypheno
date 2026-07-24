import { NextApiRequest, NextApiResponse } from "next";
import { getDb } from "@/lib/db";
import { setReadCacheHeaders } from "@/lib/cache-headers";

// Modality taxonomy for the collated overview matrix (psypheno #211). The
// `modalities` table is written by load-db from data/datasets/globals.yaml.
// Each modality is a user-facing column: an ordered list of assay-type keys it
// covers plus an `alwaysShow` flag for the expensive low-output modalities that
// must render even with zero data. The /api/collated-matrix API (#212) consumes
// this to build the matrix columns.
export interface Modality {
  key: string;
  label: string;
  assayTypes: string[];
  alwaysShow: boolean;
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  try {
    const db = getDb();

    let modalities: Modality[] = [];
    try {
      const rows = db
        .prepare(
          "SELECT key, label, assay_types, always_show FROM modalities " +
            "ORDER BY sort_order ASC"
        )
        .all() as Array<{
        key: string;
        label: string;
        assay_types: string;
        always_show: number;
      }>;
      modalities = rows.map((row) => ({
        key: row.key,
        label: row.label,
        assayTypes: JSON.parse(row.assay_types) as string[],
        alwaysShow: Boolean(row.always_show),
      }));
    } catch {
      // modalities table may not exist (older DB build) — return an empty list.
      modalities = [];
    }

    setReadCacheHeaders(res);
    return res.status(200).json({ modalities });
  } catch (err) {
    console.error("modalities handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
