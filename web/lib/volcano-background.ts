// Volcano-plot background for /api/effect-distribution, cached in-process.
//
// The background (top-by-p rows + hash-sampled bulk, their gene labels, and the
// population count) depends only on (table, perturbed gene) — never on the
// target gene. On a `/?target=SYM` gene page every table's background is the
// same for every gene, yet it costs full-table sorts/scans: ~6 s of synchronous
// better-sqlite3 work per gene page across all tables, which blocks the whole
// Node process. Caching it per (DB connection, table, perturbed gene) makes
// repeat requests nearly free. getDb() calls warmCaches() whenever it opens a
// new connection (server start or a DB swap), which precomputes the autocomplete
// lists and every table's whole-table entry in the background.
//
// The cache is keyed on the Database instance (WeakMap), so a `load-db` swap —
// which makes getDb() open a fresh connection — invalidates it automatically.

import type Database from "better-sqlite3";
import { getDb } from "@/lib/db";
import { warmSuggestions } from "@/lib/suggestions";
import {
  sanitizeIdentifier,
  parseDisplayColumns,
  parseLinkTablesForDirection,
  ALL_CONTROLS_SENTINEL_ID,
} from "@/lib/gene-query";

// Volcano sample shape: ~100 always-included top-by-p rows + a hash-sorted
// bulk sample. Numbers chosen to match the previous Python precompute so the
// frontend's cloud density looks the same.
const TOP_BY_P_LIMIT = 100;
const BULK_LIMIT = 1000;
const PVALUE_FLOOR = 1e-300;

// Per-perturbed-gene entries are bounded (LRU); whole-table entries — one per
// table — are always kept. One entry is at most ~1100 points, so this bounds
// the cache at roughly 150 MB.
const MAX_GENE_ENTRIES = 1000;

export type VolcanoPoint = {
  effect: number;
  negLog10P: number;
  fdr: number | null;
  topByP: boolean;
  // Gene symbol for this row, resolved via the table's label-direction link
  // table (target if present, else perturbed). null when the row doesn't
  // resolve to a central gene. Drives the hoverable tooltip link (#189).
  symbol: string | null;
};

type SampleRow = {
  id: number;
  effect: number | null;
  pvalue: number | null;
  fdr: number | null;
};

export type VolcanoBackground = {
  // Sanitized identifiers / parsed metadata the handler reuses for the
  // (uncached, cheap) per-target-gene query.
  baseTable: string;
  displayCols: string[];
  linkTablesRaw: string;
  effectCol: string;
  pvalueCol: string;
  fdrCol: string | null;
  // Response fields.
  effectColumn: string;
  fdrColumn: string | null;
  labelDirection: "target" | "perturbed" | null;
  nNonNull: number;
  volcanoPoints: VolcanoPoint[];
  fieldLabels: Record<string, string>;
};

export type VolcanoBackgroundResult =
  | { ok: true; background: VolcanoBackground }
  | { ok: false; error: string };

const caches = new WeakMap<Database.Database, Map<string, VolcanoBackgroundResult>>();

function cacheFor(db: Database.Database): Map<string, VolcanoBackgroundResult> {
  let cache = caches.get(db);
  if (!cache) {
    cache = new Map();
    caches.set(db, cache);
  }
  return cache;
}

/**
 * The volcano background for `tableName`, restricted to `perturbedCentralGeneId`'s
 * rows when given (and the table has a single perturbed link table). Cached;
 * callers must treat the returned object as read-only.
 */
export function getVolcanoBackground(
  db: Database.Database,
  tableName: string,
  perturbedCentralGeneId?: number,
): VolcanoBackgroundResult {
  const cache = cacheFor(db);
  // The perturbed gene only restricts the background when the table has
  // exactly one perturbed link table; otherwise share the whole-table entry
  // rather than recomputing it per gene.
  if (perturbedCentralGeneId !== undefined) {
    const meta = db
      .prepare(`SELECT link_tables FROM data_tables WHERE table_name = ?`)
      .get(tableName) as { link_tables: string | null } | undefined;
    if (parseLinkTablesForDirection(meta?.link_tables || "", "perturbed").length !== 1) {
      perturbedCentralGeneId = undefined;
    }
  }
  const key = `${tableName}|${perturbedCentralGeneId ?? ""}`;
  const hit = cache.get(key);
  if (hit) {
    // Refresh LRU position.
    cache.delete(key);
    cache.set(key, hit);
    return hit;
  }
  const result = computeVolcanoBackground(db, tableName, perturbedCentralGeneId);
  cache.set(key, result);
  if (perturbedCentralGeneId !== undefined) {
    let geneEntries = 0;
    for (const k of cache.keys()) if (!k.endsWith("|")) geneEntries++;
    for (const k of cache.keys()) {
      if (geneEntries <= MAX_GENE_ENTRIES) break;
      if (!k.endsWith("|")) {
        cache.delete(k);
        geneEntries--;
      }
    }
  }
  return result;
}

const warming = new WeakSet<Database.Database>();

/**
 * Precompute the autocomplete lists and every table's whole-table volcano
 * background, one step per macrotask so requests interleave between steps
 * (each step still blocks for its own query time — a second or two for the
 * largest table on prod). Idempotent per connection; stops early if the DB is
 * swapped mid-warm.
 */
export function warmCaches(): void {
  const db = getDb();
  if (warming.has(db)) return;
  warming.add(db);
  const tables = (
    db
      .prepare(
        `SELECT table_name FROM data_tables
         WHERE effect_column IS NOT NULL
           AND (pvalue_column IS NOT NULL OR fdr_column IS NOT NULL)
         ORDER BY table_name`,
      )
      .all() as Array<{ table_name: string }>
  ).map((r) => r.table_name);
  const steps: Array<() => void> = [
    () => warmSuggestions(db, "perturbed"),
    () => warmSuggestions(db, "target"),
    ...tables.map((t) => () => void getVolcanoBackground(db, t)),
  ];
  const run = (i: number) => {
    if (i >= steps.length) return;
    if (getDb() !== db) return; // swapped; the new connection warms itself
    try {
      steps[i]();
    } catch (err) {
      console.error("warm-up step failed", err);
    }
    setTimeout(() => run(i + 1), 50).unref();
  };
  setTimeout(() => run(0), 50).unref();
}

function computeVolcanoBackground(
  db: Database.Database,
  tableName: string,
  perturbedCentralGeneId?: number,
): VolcanoBackgroundResult {
  const tableMeta = db
    .prepare(
      `SELECT effect_column, pvalue_column, fdr_column,
              display_columns, link_tables, field_labels
       FROM data_tables WHERE table_name = ?`,
    )
    .get(tableName) as
    | {
        effect_column: string | null;
        pvalue_column: string | null;
        fdr_column: string | null;
        display_columns: string;
        link_tables: string | null;
        field_labels: string | null;
      }
    | undefined;

  // The volcano plot needs an effect column and a y-axis significance
  // column. Prefer raw p-value when available; fall back to FDR when the
  // dataset only ships FDR (e.g. perturb_fish_astro publishes qval but no
  // raw pvalue). The frontend renders `-log10(<column-name>)` from
  // `pvalueColumn`, so it'll say `-log10(qval)` automatically.
  if (
    !tableMeta ||
    !tableMeta.effect_column ||
    (!tableMeta.pvalue_column && !tableMeta.fdr_column)
  ) {
    return { ok: false, error: "Table has no effect or significance columns" };
  }

  const baseTable = sanitizeIdentifier(tableName);
  const displayCols = parseDisplayColumns(tableMeta.display_columns);
  const effectCol = sanitizeIdentifier(tableMeta.effect_column);
  const pvalueSource = tableMeta.pvalue_column || tableMeta.fdr_column!;
  const pvalueCol = sanitizeIdentifier(pvalueSource.split(",")[0]);
  const fdrCol = tableMeta.fdr_column
    ? sanitizeIdentifier(tableMeta.fdr_column.split(",")[0])
    : null;

  if (!displayCols.includes(effectCol) || !displayCols.includes(pvalueCol)) {
    return { ok: false, error: "effect/significance columns not in display_columns" };
  }

  let fieldLabels: Record<string, string> = {};
  if (tableMeta.field_labels) {
    try {
      const parsed = JSON.parse(tableMeta.field_labels);
      if (parsed && typeof parsed === "object") {
        for (const [k, v] of Object.entries(parsed)) {
          if (typeof v === "string") fieldLabels[k.toLowerCase()] = v;
        }
      }
    } catch {
      fieldLabels = {};
    }
  }

  // Background sample. When a perturbed gene is given AND this table has a
  // perturbed link direction, restrict the sample to that perturbation's
  // rows — the natural "experiment context" for a volcano. Otherwise sample
  // the whole table. The target gene never restricts the background (it
  // would shrink to 1–2 rows, just the orange dot).
  const linkTablesRaw = tableMeta.link_tables || "";
  const perturbedLTs = parseLinkTablesForDirection(linkTablesRaw, "perturbed");

  // Per-point gene labels (#189): label every background dot with the gene
  // that row is "about". Prefer the target direction (the gene whose
  // effect/p-value the row reports); fall back to perturbed for tables that
  // only carry a perturbed link (e.g. patient/variant lists). Only usable
  // when there's exactly one link table in that direction — otherwise a row
  // could map ambiguously and we leave points unlabeled.
  const targetLTs = parseLinkTablesForDirection(linkTablesRaw, "target");
  let labelDirection: "target" | "perturbed" | null = null;
  let labelLinkTable: string | null = null;
  if (targetLTs.length === 1) {
    labelDirection = "target";
    labelLinkTable = targetLTs[0];
  } else if (perturbedLTs.length === 1) {
    labelDirection = "perturbed";
    labelLinkTable = perturbedLTs[0];
  }
  let backgroundFilter = "";
  const backgroundParams: unknown[] = [];
  const isAllControls = perturbedCentralGeneId === ALL_CONTROLS_SENTINEL_ID;
  if (perturbedCentralGeneId && perturbedLTs.length === 1) {
    if (isAllControls) {
      // "All controls" → restrict the background to control-perturbation
      // rows. Inverse of the default-exclusion below; users searching
      // for controls actively want them.
      backgroundFilter = `AND b.id IN (SELECT lt.id FROM ${perturbedLTs[0]} lt JOIN central_gene cg ON cg.id = lt.central_gene_id WHERE cg.kind = 'control')`;
    } else {
      backgroundFilter = `AND b.id IN (SELECT id FROM ${perturbedLTs[0]} WHERE central_gene_id = ?)`;
      backgroundParams.push(perturbedCentralGeneId);
    }
  }

  // Exclude rows whose perturbed-gene link points at a kind='control'
  // entry (NonTarget1, SafeTarget, GFP, …). Without this, the volcano
  // background in the unrestricted case (no perturbedCentralGeneId, or
  // multiple perturbed link tables) would include control rows and
  // bias the distribution toward "no biological perturbation." Skip
  // when the user is explicitly searching for controls.
  if (!isAllControls) {
    for (const lt of perturbedLTs) {
      backgroundFilter +=
        ` AND b.id NOT IN (` +
        `SELECT lt.id FROM ${lt} lt ` +
        `JOIN central_gene cg ON cg.id = lt.central_gene_id ` +
        `WHERE cg.kind = 'control')`;
    }
  }

  const fdrSelect = fdrCol ? `b.${fdrCol}` : "NULL";
  const baseWhere = `b.${effectCol} IS NOT NULL AND b.${pvalueCol} IS NOT NULL ${backgroundFilter}`;

  // Always include the most-significant rows so the volcano's tails are
  // present regardless of the bulk sample.
  const topSql = `
    SELECT b.id AS id, b.${effectCol} AS effect, b.${pvalueCol} AS pvalue,
           ${fdrSelect} AS fdr
    FROM ${baseTable} b
    WHERE ${baseWhere}
    ORDER BY b.${pvalueCol} ASC
    LIMIT ${TOP_BY_P_LIMIT}
  `;
  // Stable pseudo-random sample: order by Knuth's multiplicative hash of
  // the row id. Deterministic per-DB; breaks insertion-order correlation
  // with effect/pvalue. The mask keeps the value in 31 bits so we never
  // overflow SQLite's int64 expression evaluator.
  const bulkSql = `
    SELECT b.id AS id, b.${effectCol} AS effect, b.${pvalueCol} AS pvalue,
           ${fdrSelect} AS fdr
    FROM ${baseTable} b
    WHERE ${baseWhere}
    ORDER BY ((b.id * 2654435761) & 2147483647)
    LIMIT ${BULK_LIMIT}
  `;
  const topRows = db.prepare(topSql).all(...backgroundParams) as SampleRow[];
  const bulkRows = db.prepare(bulkSql).all(...backgroundParams) as SampleRow[];

  // Dedup by id; top-by-p wins. Compute negLog10P here so SQLite stays
  // free of math.h.
  const seen = new Set<number>();
  const volcanoPoints: VolcanoPoint[] = [];
  // Parallel array of the source row id for each volcanoPoints entry, so we
  // can attach gene symbols after the fact (one batched lookup, below).
  const volcanoIds: number[] = [];
  const addRow = (row: SampleRow, topByP: boolean) => {
    if (seen.has(row.id)) return;
    if (row.effect == null || row.pvalue == null) return;
    const effect = Number(row.effect);
    const pvalue = Number(row.pvalue);
    if (!Number.isFinite(effect) || !Number.isFinite(pvalue)) return;
    seen.add(row.id);
    volcanoPoints.push({
      effect,
      negLog10P: -Math.log10(Math.max(pvalue, PVALUE_FLOOR)),
      fdr: row.fdr == null ? null : Number(row.fdr),
      topByP,
      symbol: null,
    });
    volcanoIds.push(row.id);
  };
  for (const r of topRows) addRow(r, true);
  for (const r of bulkRows) addRow(r, false);

  // Resolve a gene symbol per sampled row via the label-direction link
  // table. One batched query (chunked to stay under SQLite's bind-param
  // cap), preferring the HGNC human symbol, then a mouse symbol — mirrors
  // the identifier preference used across the app (#189).
  if (labelLinkTable && volcanoIds.length > 0) {
    const symbolById = resolveRowSymbols(db, labelLinkTable, volcanoIds);
    volcanoPoints.forEach((p, i) => {
      p.symbol = symbolById.get(volcanoIds[i]) ?? null;
    });
  }

  // n_nonnull is the number of rows that *would* contribute to the
  // background — i.e. the size of the (possibly-filtered) population the
  // sample is drawn from. Cheap on filtered queries; on unfiltered ones
  // it's a single scan over rows the sample queries already touched.
  const nNonNull = (
    db
      .prepare(`SELECT COUNT(*) AS cnt FROM ${baseTable} b WHERE ${baseWhere}`)
      .get(...backgroundParams) as { cnt: number }
  ).cnt;

  return {
    ok: true,
    background: {
      baseTable,
      displayCols,
      linkTablesRaw,
      effectCol,
      pvalueCol,
      fdrCol,
      effectColumn: tableMeta.effect_column,
      fdrColumn: tableMeta.fdr_column,
      labelDirection,
      nNonNull,
      volcanoPoints,
      fieldLabels,
    },
  };
}

// SQLite's default SQLITE_MAX_VARIABLE_NUMBER is 999; chunk the id list well
// under that so the IN (...) bind never overflows.
const ID_CHUNK = 500;

/**
 * Resolve one display gene symbol per row id via a link table. `linkTable`
 * is already a sanitized identifier (it came from parseLinkTablesForDirection).
 * For a row that maps to several central genes we prefer the one carrying an
 * HGNC human symbol, then a mouse symbol — matching the app-wide
 * HGNC > … identifier preference; ties broken by central_gene_id for
 * determinism. Rows with no resolvable symbol are simply absent from the map.
 */
function resolveRowSymbols(
  db: Database.Database,
  linkTable: string,
  ids: number[],
): Map<number, string> {
  const out = new Map<number, string>();
  for (let i = 0; i < ids.length; i += ID_CHUNK) {
    const chunk = ids.slice(i, i + ID_CHUNK);
    const placeholders = chunk.map(() => "?").join(", ");
    // CROSS JOIN pins the join order. A plain JOIN lets SQLite drive from
    // central_gene and probe the link table's (central_gene_id, id) primary
    // key once per gene per id — ~150k × 500 seeks, several seconds of
    // blocking on big tables. Scanning the link table is far cheaper.
    const sql = `
      SELECT lt.id AS id, cg.human_symbol AS human_symbol,
             cg.mouse_symbols AS mouse_symbols
      FROM ${linkTable} lt
      CROSS JOIN central_gene cg ON cg.id = lt.central_gene_id
      WHERE lt.id IN (${placeholders})
      ORDER BY (cg.human_symbol IS NULL), cg.id
    `;
    const rows = db.prepare(sql).all(...chunk) as Array<{
      id: number;
      human_symbol: string | null;
      mouse_symbols: string | null;
    }>;
    for (const r of rows) {
      // ORDER BY puts the preferred gene first, so keep the first symbol seen.
      if (out.has(r.id)) continue;
      const symbol = pickDisplaySymbol(r.human_symbol, r.mouse_symbols);
      if (symbol) out.set(r.id, symbol);
    }
  }
  return out;
}

/** human_symbol if present, else the first comma-separated mouse symbol. */
function pickDisplaySymbol(
  humanSymbol: string | null,
  mouseSymbols: string | null,
): string | null {
  if (humanSymbol) return humanSymbol;
  if (mouseSymbols) {
    const first = mouseSymbols
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)[0];
    return first ?? null;
  }
  return null;
}
