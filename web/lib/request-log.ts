// Request-duration and event-loop-stall logging for the production server.
//
// Why: better-sqlite3 is synchronous, so one slow request (an expensive query,
// or a read stalled on GPFS/NFS) freezes the whole process, and every other
// request — including Zabbix's check of the static home page — waits behind it.
// Each request line records wall time *and* the process CPU time spent while it
// was in flight, which separates the two causes: wall ≫ cpu means the process
// was waiting on I/O; wall ≈ cpu means it was computing. (cpuMs is process-wide,
// so concurrent requests share it — good enough to tell the cases apart.)
//
// Output: one JSON object per line, appended asynchronously (never blocks the
// event loop) to $SSPSYGENE_REQUEST_LOG, default `logs/requests.log` under the
// server's working directory (web/ on the servers). Rotated to `.1` at 50 MB.
// Files are chmod'ed 0664 so every `protein` wrangler can manage them.
//
//   {"t":"…","type":"req","method":"GET","url":"/api/…","status":200,"ms":812,"cpuMs":790,"ip":"…","ua":"…"}
//   {"t":"…","type":"stall","ms":4210}
//
// Disable with SSPSYGENE_REQUEST_LOG=off.

import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const MAX_BYTES = 50 * 1024 * 1024;
// Static assets are noisy; log them only when they are slow.
const STATIC_PREFIXES = ["/_next/static/", "/_next/image", "/favicon"];
const STATIC_MIN_MS = 1000;
const STALL_CHECK_MS = 500;
const STALL_MIN_MS = 1000;

export function shouldLog(url: string, ms: number): boolean {
  if (ms >= STATIC_MIN_MS) return true;
  return !STATIC_PREFIXES.some((p) => url.startsWith(p));
}

class RotatingLog {
  private stream: fs.WriteStream | null = null;
  private bytes = 0;

  constructor(private readonly file: string) {}

  write(entry: Record<string, unknown>): void {
    const line = JSON.stringify({ t: new Date().toISOString(), ...entry }) + "\n";
    try {
      if (!this.stream) this.open();
      if (this.bytes + line.length > MAX_BYTES) {
        this.stream!.end();
        fs.renameSync(this.file, `${this.file}.1`);
        this.open();
      }
      this.stream!.write(line);
      this.bytes += line.length;
    } catch (err) {
      // Logging must never take the site down.
      console.error(`request-log: ${(err as Error).message}`);
      this.stream = null;
    }
  }

  private open(): void {
    const dir = path.dirname(this.file);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
      fs.chmodSync(dir, 0o2775);
    }
    // Create the file synchronously so the chmod below sees it (the stream
    // opens asynchronously). The open mode is masked by the umask, hence the
    // explicit chmod.
    fs.closeSync(fs.openSync(this.file, "a", 0o664));
    try {
      fs.chmodSync(this.file, 0o664);
    } catch {
      // Not our file (another wrangler created it) — it is already shared.
    }
    this.bytes = fs.statSync(this.file).size;
    this.stream = fs.createWriteStream(this.file, { flags: "a" });
    this.stream.on("error", (err) => {
      console.error(`request-log: ${err.message}`);
      this.stream = null;
    });
  }
}

function clientIp(req: http.IncomingMessage): string | undefined {
  // Apache's ProxyPass adds X-Forwarded-For; the socket peer is always 127.0.0.1.
  const fwd = req.headers["x-forwarded-for"];
  const first = (Array.isArray(fwd) ? fwd[0] : fwd)?.split(",")[0]?.trim();
  return first || req.socket.remoteAddress;
}

let installed = false;

export function installRequestLog(): void {
  const setting = process.env.SSPSYGENE_REQUEST_LOG;
  if (installed || setting === "off") return;
  installed = true;

  const log = new RotatingLog(
    path.resolve(
      /*turbopackIgnore: true*/ setting || path.join("logs", "requests.log"),
    ),
  );

  // Patch the prototype rather than a server instance: `next start` creates
  // its http.Server outside our reach, and emit is looked up per call.
  const origEmit = http.Server.prototype.emit;
  http.Server.prototype.emit = function (
    this: http.Server,
    event: string | symbol,
    ...args: unknown[]
  ): boolean {
    if (event === "request") {
      const req = args[0] as http.IncomingMessage;
      const res = args[1] as http.ServerResponse;
      const start = process.hrtime.bigint();
      const cpuStart = process.cpuUsage();
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        const ms = Number(process.hrtime.bigint() - start) / 1e6;
        const url = (req.url ?? "").slice(0, 300);
        if (!shouldLog(url, ms)) return;
        const cpu = process.cpuUsage(cpuStart);
        log.write({
          type: "req",
          method: req.method,
          url,
          status: res.writableFinished ? res.statusCode : "aborted",
          ms: Math.round(ms),
          cpuMs: Math.round((cpu.user + cpu.system) / 1000),
          ip: clientIp(req),
          ua: String(req.headers["user-agent"] ?? "").slice(0, 160),
        });
      };
      res.once("finish", finish);
      res.once("close", finish);
    }
    return origEmit.apply(this, [event, ...args] as Parameters<typeof origEmit>);
  } as typeof http.Server.prototype.emit;

  // Event-loop stall detector: a timer that fires late means the loop was
  // blocked for the difference — whatever the cause, request or not.
  let last = Date.now();
  setInterval(() => {
    const now = Date.now();
    const lag = now - last - STALL_CHECK_MS;
    if (lag >= STALL_MIN_MS) log.write({ type: "stall", ms: lag });
    last = now;
  }, STALL_CHECK_MS).unref();
}
