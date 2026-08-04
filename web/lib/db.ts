import Database from "better-sqlite3";
import fs from "fs";
import path from "path";

let dbInstance: Database.Database | null = null;
let cachedKey: string | null = null;
let cachedPath: string | null = null;

// Status of an ATTACHed derived DB — the meta-analysis DB (sspsygene-meta.db,
// #176) or the overview-matrix DB (sspsygene-overview.db, #222) — recomputed
// whenever the connection is (re)opened. `attached` is false when the file is
// missing (initial rollout / that instance hasn't built it yet). `stale` is
// true when it was computed from a different main-DB build than the one
// currently served.
//
// Staleness compares build UUIDs (#225), not the main DB file's (mtime, size)
// as #176 originally did. That fingerprint was a property of a *file*, and
// since promotion copies files between instances, `cp` gave the target's main
// DB a fresh mtime and a correctly-promoted meta DB read as permanently stale.
// The UUID is written into the main DB by `load-db`, recorded by whatever
// derives from it, and deliberately preserved by `subset-db` — so it survives
// both the copy and the subset.
export interface MetaStatus {
  attached: boolean;
  stale: boolean;
  builtAt: string | null;
}

const UNKNOWN_STATUS: MetaStatus = {
  attached: false,
  stale: false,
  builtAt: null,
};

let metaStatus: MetaStatus = { ...UNKNOWN_STATUS };
let overviewStatus: MetaStatus = { ...UNKNOWN_STATUS };

/**
 * Resolve the meta DB path: explicit SSPSYGENE_META_DB env override, else the
 * `-meta` sibling of the main DB (sspsygene.db -> sspsygene-meta.db). Mirrors
 * the default derivation in processing/config.py.
 */
function metaDbPathFor(mainDbPath: string): string {
  const fromEnv = process.env.SSPSYGENE_META_DB;
  if (fromEnv) return path.resolve(fromEnv);
  const dir = path.dirname(mainDbPath);
  const ext = path.extname(mainDbPath); // ".db"
  const stem = path.basename(mainDbPath, ext); // "sspsygene"
  return path.join(dir, `${stem}-meta${ext}`);
}

/**
 * Resolve the overview-matrix DB path (#222): explicit SSPSYGENE_OVERVIEW_DB
 * override, else the `-overview` sibling of the main DB
 * (sspsygene.db -> sspsygene-overview.db). Mirrors metaDbPathFor and the
 * default derivation in processing/config.py.
 */
function overviewDbPathFor(mainDbPath: string): string {
  const fromEnv = process.env.SSPSYGENE_OVERVIEW_DB;
  if (fromEnv) return path.resolve(fromEnv);
  const dir = path.dirname(mainDbPath);
  const ext = path.extname(mainDbPath); // ".db"
  const stem = path.basename(mainDbPath, ext); // "sspsygene"
  return path.join(dir, `${stem}-overview${ext}`);
}

/**
 * Stat the meta DB, returning null if it doesn't exist. Used both for the
 * cache key (so a swapped-in meta DB triggers reconnection) and to gate the
 * ATTACH.
 */
function statOrNull(p: string): fs.Stats | null {
  try {
    return fs.statSync(p);
  } catch {
    return null;
  }
}

/**
 * The main DB's build UUID (#225), or null for a DB built before build_info
 * existed. Never throws — an absent table just means "unknown".
 */
function mainBuildUuid(db: Database.Database): string | null {
  try {
    const row = db
      .prepare("SELECT value FROM main.build_info WHERE key = 'build_uuid'")
      .get() as { value: string } | undefined;
    return row?.value ?? null;
  } catch {
    return null;
  }
}

/**
 * ATTACH a derived DB (if present) and compute its status against the main
 * DB's build UUID.
 *
 * `infoTable` is that DB's own key/value provenance table, which records the
 * `source_build_uuid` it was computed from. Staleness is only asserted when
 * *both* sides are known and differ: a missing build_info or a derived DB
 * predating #225 reads as attached-but-unknown-freshness, never as stale, so
 * an older DB doesn't light up a scary banner. Advisory only — never throws.
 */
function attachDerived(
  db: Database.Database,
  schema: "meta" | "overview",
  dbPath: string,
  infoTable: string,
  mainUuid: string | null
): MetaStatus {
  const status: MetaStatus = { ...UNKNOWN_STATUS };
  if (!statOrNull(dbPath)) return status;
  try {
    db.prepare(`ATTACH DATABASE ? AS ${schema}`).run(dbPath);
  } catch {
    return status; // leave detached; callers fall back to "not computed"
  }
  status.attached = true;

  try {
    const rows = db
      .prepare(`SELECT key, value FROM ${schema}.${infoTable}`)
      .all() as { key: string; value: string }[];
    const info: Record<string, string> = {};
    for (const r of rows) info[r.key] = r.value;
    status.builtAt = info["built_at"] ?? null;

    const sourceUuid = info["source_build_uuid"];
    status.stale =
      sourceUuid !== undefined && mainUuid !== null && sourceUuid !== mainUuid;
  } catch {
    // Present but missing the info table (e.g. built by an older pipeline).
    // Attached-but-unknown-freshness: not stale, no date.
    status.builtAt = null;
    status.stale = false;
  }
  return status;
}

export function getDb(): Database.Database {
  const dbPathFromEnv = process.env.SSPSYGENE_DATA_DB;
  if (!dbPathFromEnv) {
    throw new Error(
      "Environment variable SSPSYGENE_DATA_DB is not set. Please set it to the absolute path of the SQLite database file."
    );
  }
  const dbPath = path.resolve(dbPathFromEnv);
  const metaPath = metaDbPathFor(dbPath);
  const overviewPath = overviewDbPathFor(dbPath);

  // Cheap stat on every call so the process picks up a rebuilt DB (atomic
  // rename by the Python load-db pipeline changes inode + mtime) without a
  // systemd restart. Served from the dentry cache in the hot path. The meta
  // and overview DBs are statted too (issues #176, #222): rebuilding *any* of
  // the three files must reconnect so the ATTACHes and staleness status stay
  // current.
  const st = fs.statSync(dbPath);
  const metaSt = statOrNull(metaPath);
  const metaKey = metaSt
    ? `${metaSt.ino}:${metaSt.mtimeMs}:${metaSt.size}`
    : "none";
  const overviewSt = statOrNull(overviewPath);
  const overviewKey = overviewSt
    ? `${overviewSt.ino}:${overviewSt.mtimeMs}:${overviewSt.size}`
    : "none";
  const key = `${st.ino}:${st.mtimeMs}:${st.size}|${metaKey}|${overviewKey}`;

  if (dbInstance && cachedPath === dbPath && cachedKey === key) {
    return dbInstance;
  }

  if (dbInstance) {
    try {
      dbInstance.close();
    } catch {
      // The old handle may already be pointing at an unlinked inode; closing
      // is best-effort — the FD is released either way.
    }
  }

  dbInstance = new Database(dbPath, { readonly: true, fileMustExist: true });
  const mainUuid = mainBuildUuid(dbInstance);
  metaStatus = attachDerived(
    dbInstance,
    "meta",
    metaPath,
    "meta_analysis_info",
    mainUuid
  );
  overviewStatus = attachDerived(
    dbInstance,
    "overview",
    overviewPath,
    "overview_matrix_info",
    mainUuid
  );
  cachedKey = key;
  cachedPath = dbPath;
  return dbInstance;
}

/**
 * Whether a table exists in the main database.
 *
 * The DB schema moves with the Python pipeline, so a web process can be
 * serving a DB built before a table was introduced. Routes that read
 * pipeline-optional tables (LLM results, gene descriptions, the materialized
 * overview matrix) use this to degrade deliberately instead of 500ing on a
 * "no such table" error.
 */
export function tableExists(
  db: Database.Database,
  name: string,
  schema: "main" | "meta" | "overview" = "main"
): boolean {
  try {
    const row = db
      .prepare(
        `SELECT name FROM ${schema}.sqlite_master WHERE type='table' AND name=?`
      )
      .get(name) as { name: string } | undefined;
    return !!row;
  } catch {
    // No such schema — e.g. `meta` was never ATTACHed.
    return false;
  }
}

/**
 * Whether a column exists on a table.
 *
 * The column-granularity twin of {@link tableExists}, and it exists for the
 * same reason: a web process can be serving a DB built before a column was
 * introduced. That case is nastier than a missing table, because SQLite
 * resolves a SELECT's column list when the statement is *prepared* — one
 * unknown name throws before any row is read, so a single new column takes the
 * whole route down rather than blanking one field. Routes that read
 * recently-added columns select `NULL AS <col>` when this returns false, which
 * keeps the row shape (and its TypeScript type) identical.
 *
 * Cheap enough to call per request: `table_info` reads the schema the
 * connection already has open, and connections are swapped by inode on rebuild,
 * so the answer can never go stale on a live connection.
 */
export function columnExists(
  db: Database.Database,
  table: string,
  column: string,
  schema: "main" | "meta" | "overview" = "main"
): boolean {
  try {
    const cols = db.pragma(`${schema}.table_info(${table})`) as Array<{
      name: string;
    }>;
    return cols.some((c) => c.name === column);
  } catch {
    // No such table, or no such schema — e.g. `meta` was never ATTACHed.
    return false;
  }
}

/**
 * Freshness/availability of the meta-analysis DB for the current connection.
 * Call `getDb()` first (it refreshes this). Used by the combined-p-value API
 * routes to fall back gracefully when meta isn't computed, and by
 * /most-significant to render the stale/missing banner.
 */
export function getMetaStatus(): MetaStatus {
  return metaStatus;
}

/**
 * Freshness/availability of the overview-matrix DB (#222) for the current
 * connection. Call `getDb()` first (it refreshes this). Before #225 the
 * overview DB carried no staleness signal at all, so a prod instance whose
 * overview DB had gone stale looked identical to a current one.
 */
export function getOverviewStatus(): MetaStatus {
  return overviewStatus;
}
