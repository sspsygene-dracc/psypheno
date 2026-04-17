import Database from "better-sqlite3";
import fs from "fs";
import path from "path";

let dbInstance: Database.Database | null = null;
let cachedKey: string | null = null;
let cachedPath: string | null = null;

export function getDb(): Database.Database {
  const dbPathFromEnv = process.env.SSPSYGENE_DATA_DB;
  if (!dbPathFromEnv) {
    throw new Error(
      "Environment variable SSPSYGENE_DATA_DB is not set. Please set it to the absolute path of the SQLite database file."
    );
  }
  const dbPath = path.resolve(dbPathFromEnv);

  // Cheap stat on every call so the process picks up a rebuilt DB (atomic
  // rename by the Python load-db pipeline changes inode + mtime) without a
  // systemd restart. Served from the dentry cache in the hot path.
  const st = fs.statSync(dbPath);
  const key = `${st.ino}:${st.mtimeMs}:${st.size}`;

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
  cachedKey = key;
  cachedPath = dbPath;
  return dbInstance;
}
