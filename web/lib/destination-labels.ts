/**
 * Pure `deployTo` predicates shared by client and server (#225).
 *
 * Deliberately dependency-free. The badge that consumes these is a client
 * component, and `lib/destinations.ts` — where the DB read lives — imports
 * `lib/db`, which pulls in better-sqlite3 (a native module). Importing that
 * from client code drags `fs`/`bindings` into the browser bundle and Next
 * fails the build with "Module not found: Can't resolve 'fs'". Keeping the
 * predicates here means the client only ever imports plain functions.
 */

/**
 * Whether a dataset should carry the "not on production" badge.
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
