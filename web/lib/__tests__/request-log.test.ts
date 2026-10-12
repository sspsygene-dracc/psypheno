// @vitest-environment node
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { installRequestLog, shouldLog } from "@/lib/request-log";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "request-log-"));
const logFile = path.join(dir, "sub", "requests.log");

function readEntries(): Array<Record<string, unknown>> {
  if (!fs.existsSync(logFile)) return [];
  return fs
    .readFileSync(logFile, "utf8")
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((l) => JSON.parse(l));
}

async function waitFor(pred: () => boolean, ms = 3000): Promise<void> {
  const end = Date.now() + ms;
  while (!pred() && Date.now() < end) await new Promise((r) => setTimeout(r, 20));
}

describe("shouldLog", () => {
  it("skips fast static assets but keeps slow ones and everything else", () => {
    expect(shouldLog("/_next/static/chunks/a.js", 5)).toBe(false);
    expect(shouldLog("/_next/static/chunks/a.js", 1500)).toBe(true);
    expect(shouldLog("/", 2)).toBe(true);
    expect(shouldLog("/api/full-datasets", 2)).toBe(true);
  });
});

describe("installRequestLog", () => {
  let server: http.Server;
  let port: number;

  beforeAll(async () => {
    process.env.SSPSYGENE_REQUEST_LOG = logFile;
    installRequestLog();
    server = http.createServer((req, res) => {
      if (req.url === "/block") {
        // Synchronous work, like a slow better-sqlite3 query.
        const end = Date.now() + 1700;
        while (Date.now() < end);
      }
      res.end("ok");
    });
    await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
    port = (server.address() as { port: number }).port;
  });

  afterAll(() => {
    server.close();
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("logs each request with status, wall time, CPU time and forwarded IP", async () => {
    await fetch(`http://127.0.0.1:${port}/api/x?y=1`, {
      headers: { "x-forwarded-for": "203.0.113.7, 10.0.0.1", "user-agent": "TestBot" },
    });
    await waitFor(() => readEntries().some((e) => e.url === "/api/x?y=1"));
    const e = readEntries().find((x) => x.url === "/api/x?y=1")!;
    expect(e).toMatchObject({ type: "req", method: "GET", status: 200, ip: "203.0.113.7", ua: "TestBot" });
    expect(typeof e.ms).toBe("number");
    expect(typeof e.cpuMs).toBe("number");
    // Group-writable on the shared servers.
    expect(fs.statSync(logFile).mode & 0o777).toBe(0o664);
  });

  it("records a blocking request as CPU-bound and logs the event-loop stall", async () => {
    await fetch(`http://127.0.0.1:${port}/block`);
    await waitFor(() => readEntries().some((e) => e.type === "stall"));
    const req = readEntries().find((e) => e.url === "/block")!;
    expect(req.ms as number).toBeGreaterThanOrEqual(1600);
    expect(req.cpuMs as number).toBeGreaterThanOrEqual(1000);
    const stall = readEntries().find((e) => e.type === "stall")!;
    expect(stall.ms as number).toBeGreaterThanOrEqual(1000);
  });
});
