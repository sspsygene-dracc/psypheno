import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb, tableExists } from "@/lib/db";
import { setReadCacheHeaders } from "@/lib/cache-headers";

/**
 * GET /api/region-genes?tables=a,b,c — the perturbed genes of the given
 * perturbation tables and what changed, for the /regions panel.
 *
 * Reads the overview DB's per-dataset summary (`overview_matrix_summary_cells`:
 * source_table × perturbed gene → readouts significant / measured), so it
 * covers exactly the tables that feed the overview matrix. Tables that aren't
 * matrix sources are listed under `notInMatrix`. If the overview DB is absent
 * the response is empty with `available: false`, never a 500.
 */

const MAX_TABLES = 100;
const MAX_GENES_PER_TABLE = 2000;

const querySchema = z.object({
  tables: z
    .string()
    .max(10_000)
    .transform((s) =>
      Array.from(new Set(s.split(",").map((t) => t.trim()).filter(Boolean))),
    )
    .refine((a) => a.length <= MAX_TABLES)
    .refine((a) => a.every((t) => /^[A-Za-z0-9_]+$/.test(t))),
});

export type RegionGene = {
  centralGeneId: number;
  symbol: string | null;
  nSig: number;
  nMeasured: number;
};

export type RegionGenesTable = {
  sourceTable: string;
  modalityKey: string;
  /** What nSig counts: "fdr<0.05" or "nominal_p<0.05". */
  sigRule: string;
  nReadoutsTotal: number;
  /** Perturbed genes with a summary cell (before truncation). */
  nGenes: number;
  /** Most significant readouts first; at most MAX_GENES_PER_TABLE. */
  genes: RegionGene[];
};

export type RegionGenesResponse = {
  available: boolean;
  tables: RegionGenesTable[];
  notInMatrix: string[];
};

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<RegionGenesResponse | { error: string }>,
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  const parsed = querySchema.safeParse(req.query);
  if (!parsed.success) {
    return res.status(400).json({ error: "Invalid query parameters" });
  }
  const requested = parsed.data.tables;

  try {
    const db = getDb();
    const available =
      tableExists(db, "overview_matrix_summary_columns", "overview") &&
      tableExists(db, "overview_matrix_summary_cells", "overview");
    if (!available || requested.length === 0) {
      setReadCacheHeaders(res);
      return res
        .status(200)
        .json({ available, tables: [], notInMatrix: available ? [] : requested });
    }

    const placeholders = requested.map(() => "?").join(",");
    const columns = db
      .prepare(
        `SELECT source_table, modality_key, sig_rule, n_readouts_total
           FROM overview.overview_matrix_summary_columns
          WHERE source_table IN (${placeholders})`,
      )
      .all(...requested) as Array<{
      source_table: string;
      modality_key: string;
      sig_rule: string;
      n_readouts_total: number;
    }>;
    const inMatrix = new Set(columns.map((c) => c.source_table));

    // Symbol: the matrix's own gene table, else the central gene table (a
    // mouse-only gene has no human symbol — show its mouse symbol).
    const cellStmt = db.prepare(
      `SELECT c.central_gene_id AS id, c.n_sig AS nSig, c.n_measured AS nMeasured,
              COALESCE(g.human_symbol, cg.human_symbol, cg.mouse_symbols) AS symbol
         FROM overview.overview_matrix_summary_cells c
         LEFT JOIN overview.overview_matrix_genes g
           ON g.central_gene_id = c.central_gene_id
         LEFT JOIN main.central_gene cg ON cg.id = c.central_gene_id
        WHERE c.source_table = ?
        ORDER BY c.n_sig DESC, c.n_measured DESC, symbol ASC`,
    );

    const tables: RegionGenesTable[] = columns
      .map((c) => {
        const rows = cellStmt.all(c.source_table) as Array<{
          id: number;
          nSig: number;
          nMeasured: number;
          symbol: string | null;
        }>;
        return {
          sourceTable: c.source_table,
          modalityKey: c.modality_key,
          sigRule: c.sig_rule,
          nReadoutsTotal: c.n_readouts_total,
          nGenes: rows.length,
          genes: rows.slice(0, MAX_GENES_PER_TABLE).map((r) => ({
            centralGeneId: r.id,
            // mouse_symbols can be a comma list; the first is the display name.
            symbol: r.symbol ? r.symbol.split(",")[0].trim() : null,
            nSig: r.nSig,
            nMeasured: r.nMeasured,
          })),
        };
      })
      .sort((a, b) => requested.indexOf(a.sourceTable) - requested.indexOf(b.sourceTable));

    setReadCacheHeaders(res);
    return res.status(200).json({
      available: true,
      tables,
      notInMatrix: requested.filter((t) => !inMatrix.has(t)),
    });
  } catch (err) {
    console.error("region-genes handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
