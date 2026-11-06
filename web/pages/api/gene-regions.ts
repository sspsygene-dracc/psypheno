import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb, tableExists } from "@/lib/db";
import { setReadCacheHeaders } from "@/lib/cache-headers";
import { fetchGeneSuggestions } from "@/lib/suggestions";
import {
  buildGeneQuery,
  parseDisplayColumns,
  parseLinkTablesForDirection,
  sanitizeIdentifier,
} from "@/lib/gene-query";
import { NOT_PERTURBED_TABLES } from "@/lib/brain-regions";

/**
 * GET /api/gene-regions — which tables a gene query matches, for the gene
 * view of /regions. Same semantics as the home page search:
 *
 *   ?perturbed=X            tables where X is a perturbed gene (the table's
 *                           perturbed-gene column);
 *   ?target=Y               tables where Y is a measured / target gene
 *                           (readout, DE gene, associated gene);
 *   ?perturbed=X&target=Y   tables with a row where X was perturbed and Y
 *                           measured (the home page's pair search);
 *   ?gene=Z                 old links: Z perturbed *or* measured.
 *
 * "Matched" means the gene appears there, not that it is significant. Tables
 * in NOT_PERTURBED_TABLES never match on their perturbed column (it isn't a
 * perturbation); they're listed under `excluded` when they would have. For
 * perturbed-only queries on overview-matrix tables it adds the gene's
 * significant / measured readout counts. The page places the tables on the
 * drawings with the same region rules as the dataset view.
 */

const symbol = z.string().trim().min(1).max(64);
const querySchema = z
  .object({
    perturbed: symbol.optional(),
    target: symbol.optional(),
    gene: symbol.optional(),
  })
  .refine((q) => q.perturbed || q.target || q.gene);

export type GeneRef = { centralGeneId: number; symbol: string; humanSymbol: string | null };

/** How the query matched a table. */
export type GeneMatchRole = "perturbed" | "measured" | "pair";

export type GeneRegionsTable = {
  table: string;
  role: GeneMatchRole;
  /** Overview-matrix summary for a perturbed gene, when the table is a matrix source. */
  nSig?: number;
  nMeasured?: number;
  sigRule?: string;
};

export type GeneRegionsResponse = {
  perturbed: GeneRef | null;
  target: GeneRef | null;
  /** ?gene= alias: the gene, perturbed or measured. */
  either: GeneRef | null;
  /** Symbols in the query that matched no gene. */
  notFound: string[];
  tables: GeneRegionsTable[];
  /** Tables left out on purpose (NOT_PERTURBED_TABLES), with the reason. */
  excluded: Array<{ table: string; reason: string }>;
};

/** Same resolution as the home page: exact human symbol, exact mouse-only symbol, else the best suggestion. */
function resolve(query: string): GeneRef | null {
  const suggestions = fetchGeneSuggestions(query, 8).filter((s) => s.centralGeneId >= 0);
  const upper = query.toUpperCase();
  const pick =
    suggestions.find((s) => s.humanSymbol?.toUpperCase() === upper) ??
    suggestions.find((s) => !s.humanSymbol && (s.mouseSymbols ?? []).some((m) => m.toUpperCase() === upper)) ??
    suggestions[0] ??
    null;
  if (!pick) return null;
  return {
    centralGeneId: pick.centralGeneId,
    symbol: pick.displayLabel ?? pick.humanSymbol ?? query,
    humanSymbol: pick.humanSymbol,
  };
}

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
  const q = parsed.data;

  try {
    const pairMode = !!(q.perturbed || q.target);
    const perturbed = pairMode && q.perturbed ? resolve(q.perturbed) : null;
    const target = pairMode && q.target ? resolve(q.target) : null;
    const either = !pairMode && q.gene ? resolve(q.gene) : null;
    const notFound = [
      ...(pairMode && q.perturbed && !perturbed ? [q.perturbed] : []),
      ...(pairMode && q.target && !target ? [q.target] : []),
      ...(!pairMode && q.gene && !either ? [q.gene] : []),
    ];
    const empty: GeneRegionsResponse = { perturbed, target, either, notFound, tables: [], excluded: [] };
    setReadCacheHeaders(res);
    if (notFound.length > 0) return res.status(200).json(empty);

    const db = getDb();
    const rows = db
      .prepare("SELECT table_name, link_tables, display_columns FROM data_tables ORDER BY table_name")
      .all() as Array<{ table_name: string; link_tables: string | null; display_columns: string }>;

    // One row with the given perturbed / target gene ids (either may be
    // null), exactly as the home page's gene search builds it.
    const hasRow = (r: (typeof rows)[number], p: number | null, t: number | null): boolean => {
      const displayCols = parseDisplayColumns(r.display_columns);
      if (displayCols.length === 0) return false;
      const built = buildGeneQuery({
        baseTable: sanitizeIdentifier(r.table_name),
        displayCols,
        linkTablesRaw: r.link_tables ?? "",
        perturbedCentralGeneId: p,
        targetCentralGeneId: t,
      });
      if (!built) return false;
      return !!db.prepare(`SELECT 1 ${built.fromAndWhere} LIMIT 1`).get(...built.params);
    };
    const inLinkTables = (r: (typeof rows)[number], dir: "perturbed" | "target", id: number) =>
      parseLinkTablesForDirection(r.link_tables ?? "", dir).some(
        (lt) => !!db.prepare(`SELECT 1 FROM ${lt} WHERE central_gene_id = ? LIMIT 1`).get(id),
      );

    const tables: GeneRegionsTable[] = [];
    const excluded: GeneRegionsResponse["excluded"] = [];
    for (const r of rows) {
      const notPerturbed = NOT_PERTURBED_TABLES[r.table_name];
      if (either) {
        const isPert = inLinkTables(r, "perturbed", either.centralGeneId);
        const isMeas = inLinkTables(r, "target", either.centralGeneId);
        if (isPert && notPerturbed) {
          excluded.push({ table: r.table_name, reason: notPerturbed });
          if (isMeas) tables.push({ table: r.table_name, role: "measured" });
        } else if (isPert) {
          tables.push({ table: r.table_name, role: "perturbed" });
        } else if (isMeas) {
          tables.push({ table: r.table_name, role: "measured" });
        }
        continue;
      }
      const p = perturbed?.centralGeneId ?? null;
      const t = target?.centralGeneId ?? null;
      if (!hasRow(r, p, t)) continue;
      if (p !== null && notPerturbed) {
        excluded.push({ table: r.table_name, reason: notPerturbed });
        continue;
      }
      tables.push({ table: r.table_name, role: p !== null && t !== null ? "pair" : p !== null ? "perturbed" : "measured" });
    }

    // Readout counts for a perturbed gene (perturbed-only queries).
    const countsFor = perturbed && !target ? perturbed : either;
    if (
      countsFor &&
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
        .all(countsFor.centralGeneId) as Array<{ t: string; nSig: number; nMeasured: number; sigRule: string }>;
      for (const s of summary) {
        const t = tables.find((x) => x.table === s.t);
        if (t && t.role === "perturbed") Object.assign(t, { nSig: s.nSig, nMeasured: s.nMeasured, sigRule: s.sigRule });
      }
    }

    return res.status(200).json({ ...empty, tables, excluded });
  } catch (err) {
    console.error("gene-regions handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
