import type Database from "better-sqlite3";
import { tableExists } from "@/lib/db";

/**
 * Per-table `deployTo` destinations, read from the `dataset_destinations`
 * table that `load-db` writes (#225).
 *
 * This is what drives the "not on production" flag in the UI. A wrangler
 * loading an embargoed dataset onto dev needs to see, at a glance, that it is
 * still marked dev/int-only — *before* they promote. The flag is derived from
 * the same table the destination guard checks, so what the UI shows and what
 * a promotion would actually do cannot drift apart.
 *
 * Returns an empty map for a DB built before #225, which renders no badges at
 * all rather than mislabelling every dataset as embargoed.
 */
export function loadDestinations(
  db: Database.Database
): Map<string, string[]> {
  const out = new Map<string, string[]>();
  if (!tableExists(db, "dataset_destinations")) return out;
  try {
    const rows = db
      .prepare(
        "SELECT table_name, destination FROM dataset_destinations " +
          "ORDER BY table_name, destination"
      )
      .all() as { table_name: string; destination: string }[];
    for (const r of rows) {
      const list = out.get(r.table_name) ?? [];
      list.push(r.destination);
      out.set(r.table_name, list);
    }
  } catch {
    // Malformed/old schema — treat as unknown rather than failing the request.
  }
  return out;
}

/** Instance this web process is serving, from SSPSYGENE_INSTANCE (default dev). */
export function currentInstance(): string {
  return process.env.SSPSYGENE_INSTANCE || "dev";
}

/**
 * Whether a dataset should carry the "not on production" badge (#225).
 *
 * True only when we positively know the dataset is NOT cleared for prod. An
 * unknown/empty destination list (a DB built before #225) returns false: the
 * badge exists to warn, so a missing badge must never be read as "confirmed
 * public".
 */
export function isRestricted(destinations?: string[] | null): boolean {
  const set = new Set(destinations ?? []);
  if (set.size === 0) return false;
  return !set.has("prod");
}

/** Badge text for a restricted dataset, or null when no badge should show. */
export function restrictionLabel(
  destinations?: string[] | null
): "Internal only" | "Dev only" | null {
  if (!isRestricted(destinations)) return null;
  return new Set(destinations ?? []).has("int") ? "Internal only" : "Dev only";
}
