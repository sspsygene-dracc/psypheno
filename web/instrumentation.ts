// Next.js server-startup hook (runs once per server process).
//
// Note: this file is bundled separately from the API routes, so it must not
// rely on module-level state they share (e.g. getDb's connection or the
// volcano cache) — those would be different copies here. The request log is
// fine: it patches the global http.Server prototype.
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { installRequestLog } = await import("./lib/request-log");
    installRequestLog();
  }
}
