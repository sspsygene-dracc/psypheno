import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb, tableExists } from "@/lib/db";
import { setReadCacheHeaders } from "@/lib/cache-headers";
import type {
  CollatedCellResponse,
  CollatedContribution,
} from "@/lib/collated-matrix-types";

/**
 * GET /api/collated-cell — the studies behind one cell of the collated
 * (by-readout) matrix: for a (perturbed gene, readout gene) pair, each study
 * that measured it, with its best FDR / p, effect, number of tests and whether
 * it counted as significant. Loaded on click so the matrix payload stays lean.
 */

const querySchema = z.object({
  group: z.string().regex(/^[a-z0-9_]+$/),
  perturbed: z.coerce.number().int().nonnegative(),
  // Phenotype columns are terms, which take negative ids.
  target: z.coerce.number().int(),
});

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<CollatedCellResponse | { error: string }>
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  const parsed = querySchema.safeParse(req.query);
  if (!parsed.success) {
    return res.status(400).json({ error: "Invalid query parameters" });
  }
  const { group, perturbed, target } = parsed.data;

  try {
    const db = getDb();
    if (!tableExists(db, "overview_matrix_collated_contrib", "overview")) {
      setReadCacheHeaders(res);
      return res.status(200).json({ contributions: [] });
    }
    const rows = db
      .prepare(
        `SELECT study, study_label, source_tables, n_tests, min_fdr, best_p,
                effect, significant, inferred_basis
           FROM overview.overview_matrix_collated_contrib
          WHERE collate_group = ? AND target_gene_id = ? AND central_gene_id = ?
          ORDER BY significant DESC, study_label ASC`
      )
      .all(group, target, perturbed) as Array<{
      study: string;
      study_label: string;
      source_tables: string;
      n_tests: number;
      min_fdr: number | null;
      best_p: number | null;
      effect: number | null;
      significant: number;
      inferred_basis: string | null;
    }>;
    const contributions: CollatedContribution[] = rows.map((r) => ({
      study: r.study,
      studyLabel: r.study_label,
      sourceTables: r.source_tables,
      nTests: r.n_tests,
      minFdr: r.min_fdr,
      bestP: r.best_p,
      effect: r.effect,
      significant: r.significant === 1,
      inferredBasis:
        r.inferred_basis === "library" || r.inferred_basis === "screen"
          ? r.inferred_basis
          : null,
    }));
    setReadCacheHeaders(res);
    return res.status(200).json({ contributions });
  } catch (err) {
    console.error("collated-cell failed", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
