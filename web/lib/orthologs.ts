import type Database from "better-sqlite3";

// Mouse genes with several human orthologs and no single best match stay
// mouse-only in central_gene; load-db stores their candidates as JSON in
// central_gene.candidate_human_orthologs ([{hgnc_id, symbol, central_gene_id}]).
// These helpers surface them on the gene page, in both directions.

export type CandidateOrtholog = {
  hgncId: string;
  symbol: string;
  // Null when the candidate human gene is not in this DB (no dataset uses it),
  // so there is nothing to link to.
  centralGeneId: number | null;
};

export type OrthologOf = {
  centralGeneId: number;
  mouseSymbol: string;
};

export type OrthologNotes = {
  // On a mouse-only gene: its candidate human orthologs.
  candidates: CandidateOrtholog[];
  // On a human gene: the mouse-only genes that list it as a candidate.
  candidateOf: OrthologOf[];
};

type RawCandidate = { hgnc_id?: unknown; symbol?: unknown; central_gene_id?: unknown };

/** Parse the stored JSON; tolerant of null / malformed values. `centralGeneId`
 * is left as stored — callers check it against the DB. */
export function parseCandidateOrthologs(raw: string | null | undefined): CandidateOrtholog[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const out: CandidateOrtholog[] = [];
  for (const c of parsed as RawCandidate[]) {
    if (!c || typeof c.symbol !== "string" || typeof c.hgnc_id !== "string") continue;
    out.push({
      hgncId: c.hgnc_id,
      symbol: c.symbol,
      centralGeneId: typeof c.central_gene_id === "number" ? c.central_gene_id : null,
    });
  }
  return out;
}

// hgnc_id -> mouse-only genes naming it as a candidate. Built once per DB
// connection; getDb() swaps the connection after a rebuild, so keying on the
// instance self-invalidates.
const reverseIndexCache = new WeakMap<Database.Database, Map<string, OrthologOf[]>>();

function reverseIndex(db: Database.Database): Map<string, OrthologOf[]> {
  const cached = reverseIndexCache.get(db);
  if (cached) return cached;
  const index = new Map<string, OrthologOf[]>();
  const rows = db
    .prepare(
      `SELECT id, mouse_symbols, candidate_human_orthologs FROM central_gene
       WHERE candidate_human_orthologs IS NOT NULL`,
    )
    .all() as Array<{ id: number; mouse_symbols: string | null; candidate_human_orthologs: string }>;
  for (const r of rows) {
    const mouseSymbol = (r.mouse_symbols ?? "").split(",").filter(Boolean)[0];
    if (!mouseSymbol) continue;
    for (const c of parseCandidateOrthologs(r.candidate_human_orthologs)) {
      const list = index.get(c.hgncId) ?? [];
      list.push({ centralGeneId: r.id, mouseSymbol });
      index.set(c.hgncId, list);
    }
  }
  for (const list of index.values()) {
    list.sort((a, b) => a.mouseSymbol.localeCompare(b.mouseSymbol));
  }
  reverseIndexCache.set(db, index);
  return index;
}

/** Ortholog notes for one gene. Returns empty notes on a DB built before the
 * candidate_human_orthologs column existed. */
export function getOrthologNotes(db: Database.Database, centralGeneId: number): OrthologNotes {
  const empty: OrthologNotes = { candidates: [], candidateOf: [] };
  let row: { hgnc_id: string | null; candidate_human_orthologs: string | null } | undefined;
  try {
    row = db
      .prepare("SELECT hgnc_id, candidate_human_orthologs FROM central_gene WHERE id = ?")
      .get(centralGeneId) as typeof row;
  } catch {
    return empty; // column absent in an older DB
  }
  if (!row) return empty;

  let candidates = parseCandidateOrthologs(row.candidate_human_orthologs);
  const ids = candidates.map((c) => c.centralGeneId).filter((x): x is number => x != null);
  if (ids.length > 0) {
    const present = new Set(
      (
        db
          .prepare(`SELECT id FROM central_gene WHERE id IN (${ids.map(() => "?").join(",")})`)
          .all(...ids) as Array<{ id: number }>
      ).map((r) => r.id),
    );
    candidates = candidates.map((c) => ({
      ...c,
      centralGeneId: c.centralGeneId != null && present.has(c.centralGeneId) ? c.centralGeneId : null,
    }));
  }

  const candidateOf = row.hgnc_id ? (reverseIndex(db).get(row.hgnc_id) ?? []) : [];
  return { candidates, candidateOf };
}
