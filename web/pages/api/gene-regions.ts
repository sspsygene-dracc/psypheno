import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb, tableExists } from "@/lib/db";
import { setReadCacheHeaders } from "@/lib/cache-headers";
import { fetchGeneSuggestions } from "@/lib/suggestions";
import { parseLinkTablesForDirection, sanitizeIdentifier } from "@/lib/gene-query";

/**
 * GET /api/gene-regions?gene=SYMBOL — where a gene's data come from, for the
 * gene view of /regions: every table in which the gene was perturbed or
 * appears as a measured gene (readout / DE gene / association), found through
 * the tables' perturbed / target link tables. For perturbation tables in the
 * overview matrix it adds the gene's significant / measured readout counts.
 * The page places the tables on the drawings with the same region rules as
 * the dataset view.
 */

const querySchema = z.object({ gene: z.string().trim().min(1).max(64) });

export type GeneRegionsTable = {
  table: string;
  perturbed: boolean;
  measured: boolean;
  /** Overview-matrix summary for a perturbed gene, when the table is a matrix source. */
  nSig?: number;
  nMeasured?: number;
  sigRule?: string;
};

export type GeneRegionsResponse = {
  gene: { centralGeneId: number; symbol: string; humanSymbol: string | null } | null;
  tables: GeneRegionsTable[];
};

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<GeneRegionsResponse | { error: string }>,
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  const parsed = querySchema.safeParse(req.query);
  if (!parsed.success) {
    return res.status(400).json({ error: "Invalid query parameters" });
  }
  const query = parsed.data.gene;

  try {
    // Same resolution as the home page: exact human symbol, else exact mouse
    // symbol, else the best suggestion. Controls are not genes here.
    const suggestions = fetchGeneSuggestions(query, 8).filter((s) => s.centralGeneId >= 0);
    const upper = query.toUpperCase();
    const pick =
      suggestions.find((s) => s.humanSymbol?.toUpperCase() === upper) ??
      suggestions.find((s) => (s.mouseSymbols ?? []).some((m) => m.toUpperCase() === upper)) ??
      suggestions[0] ??
      null;
    setReadCacheHeaders(res);
    if (!pick) return res.status(200).json({ gene: null, tables: [] });
    const id = pick.centralGeneId;

    const db = getDb();
    const rows = db
      .prepare("SELECT table_name, link_tables FROM data_tables ORDER BY table_name")
      .all() as Array<{ table_name: string; link_tables: string | null }>;

    const has = (lt: string) =>
      !!db.prepare(`SELECT 1 FROM ${sanitizeIdentifier(lt)} WHERE central_gene_id = ? LIMIT 1`).get(id);

    const tables: GeneRegionsTable[] = [];
    for (const r of rows) {
      const raw = r.link_tables ?? "";
      const perturbed = parseLinkTablesForDirection(raw, "perturbed").some(has);
      const measured = parseLinkTablesForDirection(raw, "target").some(has);
      if (perturbed || measured) tables.push({ table: r.table_name, perturbed, measured });
    }

    if (
      tableExists(db, "overview_matrix_summary_cells", "overview") &&
      tableExists(db, "overview_matrix_summary_columns", "overview")
    ) {
      const summary = db
        .prepare(
          `SELECT c.source_table AS t, c.n_sig AS nSig, c.n_measured AS nMeasured, s.sig_rule AS sigRule
             FROM overview.overview_matrix_summary_cells c
             JOIN overview.overview_matrix_summary_columns s ON s.source_table = c.source_table
            WHERE c.central_gene_id = ?`,
        )
        .all(id) as Array<{ t: string; nSig: number; nMeasured: number; sigRule: string }>;
      for (const s of summary) {
        const t = tables.find((x) => x.table === s.t);
        if (t && t.perturbed) Object.assign(t, { nSig: s.nSig, nMeasured: s.nMeasured, sigRule: s.sigRule });
      }
    }

    return res.status(200).json({
      gene: {
        centralGeneId: id,
        symbol: pick.displayLabel ?? pick.humanSymbol ?? query,
        humanSymbol: pick.humanSymbol,
      },
      tables,
    });
  } catch (err) {
    console.error("gene-regions handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
