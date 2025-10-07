import Database from "better-sqlite3";
import path from "path";

let dbInstance: Database.Database | null = null;

export function getDb(): Database.Database {
  if (dbInstance) return dbInstance;
  // Absolute path to the SQLite DB alongside the repo's data directory
  const dbPath = path.resolve(
    "/Users/jbirgmei/prog/sspsygene/data/db/sspsygene.db"
  );
  dbInstance = new Database(dbPath, { readonly: true, fileMustExist: true });
  return dbInstance;
}
