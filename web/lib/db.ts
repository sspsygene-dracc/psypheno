import Database from "better-sqlite3";
import fs from "fs";
import path from "path";

let dbInstance: Database.Database | null = null;
let cachedKey: string | null = null;
let cachedPath: string | null = null;

// Status of the ATTACHed meta-analysis DB (sspsygene-meta.db, issue #176),
// recomputed whenever the connection is (re)opened. `attached` is false when
// the meta DB file is missing (initial rollout / instance hasn't run
// `sspsygene meta-analysis` yet). `stale` is true when the meta DB was built
// against an older dataset DB than the one currently served (any `load-db`
// rebuild mints a new mtime/size, so this flips on until meta is re-run).
export interface MetaStatus {
  attached: boolean;
  stale: boolean;
  builtAt: string | null;
}

let metaStatus: MetaStatus = { attached: false, stale: false, builtAt: null };

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
 * Attach the meta DB (if present) and refresh `metaStatus`. Staleness compares
 * the dataset-DB fingerprint recorded at meta-build time against the live main
 * DB stat: a size mismatch, or a whole-second mtime mismatch, means the
 * datasets have been rebuilt since the meta-analysis last ran. Advisory only —
 * never throws on a malformed/old meta DB.
 */
function attachMeta(db: Database.Database, metaPath: string, mainStat: fs.Stats): void {
  metaStatus = { attached: false, stale: false, builtAt: null };
  if (!statOrNull(metaPath)) return;
  try {
    db.prepare("ATTACH DATABASE ? AS meta").run(metaPath);
  } catch {
    return; // leave detached; callers fall back to "meta not computed"
  }
  metaStatus.attached = true;

  try {
    const rows = db
      .prepare("SELECT key, value FROM meta.meta_analysis_info")
      .all() as { key: string; value: string }[];
    const info: Record<string, string> = {};
    for (const r of rows) info[r.key] = r.value;
    metaStatus.builtAt = info["built_at"] ?? null;

    const recordedSize = info["source_db_size"];
    const recordedMtime = info["source_db_mtime"];
    const sizeMismatch =
      recordedSize !== undefined && Number(recordedSize) !== mainStat.size;
    const mtimeMismatch =
      recordedMtime !== undefined &&
      Math.floor(parseFloat(recordedMtime)) !==
        Math.floor(mainStat.mtimeMs / 1000);
    metaStatus.stale = sizeMismatch || mtimeMismatch;
  } catch {
    // Meta DB present but missing the info table (e.g. built by an older
    // pipeline). Treat as attached-but-unknown-freshness: not stale, no date.
    metaStatus.builtAt = null;
    metaStatus.stale = false;
  }
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

  // Cheap stat on every call so the process picks up a rebuilt DB (atomic
  // rename by the Python load-db pipeline changes inode + mtime) without a
  // systemd restart. Served from the dentry cache in the hot path. The meta
  // DB is statted too (issue #176): rebuilding *either* file must reconnect so
  // the ATTACH and staleness status stay current.
  const st = fs.statSync(dbPath);
  const metaSt = statOrNull(metaPath);
  const metaKey = metaSt
    ? `${metaSt.ino}:${metaSt.mtimeMs}:${metaSt.size}`
    : "none";
  const key = `${st.ino}:${st.mtimeMs}:${st.size}|${metaKey}`;

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
  attachMeta(dbInstance, metaPath, st);
  cachedKey = key;
  cachedPath = dbPath;
  return dbInstance;
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
