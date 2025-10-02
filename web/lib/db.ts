import Database from 'better-sqlite3';
import path from 'path';

let dbInstance: Database.Database | null = null;

export function getDb(): Database.Database {
  if (dbInstance) return dbInstance;
  // Absolute path to the SQLite DB alongside the repo's data directory
  const dbPath = path.resolve('/Users/jbirgmei/prog/sspsygene/data/pheno/pheno.db');
  dbInstance = new Database(dbPath, { readonly: true, fileMustExist: true });
  return dbInstance;
}

export type SortOrder = 'asc' | 'desc';

export function buildOrderBy(sortby?: string | null, sortorder?: SortOrder | null): string {
  if (!sortby) return '';
  const orderDir = sortorder === 'desc' ? 'DESC' : 'ASC';
  const special = sortby === 'chrom' ? 'chrom,start,end' : sortby;
  return ` ORDER BY ${special} ${orderDir}`;
}

export function buildLimit(page?: number | null, perPage?: number | null): string {
  if (!page || !perPage) return '';
  const from = (page - 1) * perPage;
  return ` LIMIT ${perPage} OFFSET ${from}`;
}

