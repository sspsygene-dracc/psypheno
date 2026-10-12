// Next.js server-startup hook (runs once per server process).
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { installRequestLog } = await import("./lib/request-log");
    installRequestLog();
  }
}
