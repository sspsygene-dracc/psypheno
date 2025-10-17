import Database from "better-sqlite3";
import path from "path";

let dbInstance: Database.Database | null = null;

export function getDb(): Database.Database {
  if (dbInstance) return dbInstance;
  // Read SQLite DB path from environment variable
  const dbPathFromEnv = process.env.SSPSYGENE_DATA_DB;
  if (!dbPathFromEnv) {
    throw new Error(
      "Environment variable SSPSYGENE_DATA_DB is not set. Please set it to the absolute path of the SQLite database file."
    );
  }
  const dbPath = path.resolve(dbPathFromEnv);
  dbInstance = new Database(dbPath, { readonly: true, fileMustExist: true });
  return dbInstance;
}
