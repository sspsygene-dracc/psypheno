import type { NextApiResponse } from "next";

// Read-API cache policy: serve from cache for up to ~2 min after a fetch,
// with a background revalidate in the second half of that window.
//
// 0–60 s after a fetch: served instantly from cache.
// 60–120 s: served from cache *and* revalidates in the background.
// >120 s: blocking revalidate.
//
// Worst-case post-rebuild staleness for a tab already open is ~2 min; new
// tabs / hard reloads see the new data immediately. Wranglers are told the
// site can serve up to ~2 min stale data after a `load-db`.
export function setReadCacheHeaders(res: NextApiResponse): void {
  res.setHeader(
    "Cache-Control",
    "public, max-age=60, stale-while-revalidate=60",
  );
}
