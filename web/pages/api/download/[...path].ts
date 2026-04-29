/**
 * Serves files out of `<SSPSYGENE_DATA_DB dir>/exports/`, the user-facing
 * download tree built by `sspsygene load-db`. Streams binaries (zip, sqlite)
 * with `Content-Disposition: attachment` so browsers prompt to save.
 *
 * Path-traversal guard: the joined path is resolved and must remain inside
 * the exports root.
 */
import type { NextApiRequest, NextApiResponse } from "next";
import fs from "fs";
import path from "path";

export const config = {
  api: { bodyParser: false, responseLimit: false },
};

const MIME_TYPES: Record<string, string> = {
  ".tsv": "text/tab-separated-values; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".yaml": "application/x-yaml; charset=utf-8",
  ".yml": "application/x-yaml; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".zip": "application/zip",
  ".db": "application/vnd.sqlite3",
  ".sqlite": "application/vnd.sqlite3",
};

function exportsRoot(): string {
  const dbPath = process.env.SSPSYGENE_DATA_DB;
  if (!dbPath) {
    throw new Error("SSPSYGENE_DATA_DB is not set");
  }
  return path.resolve(path.dirname(dbPath), "exports");
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse,
) {
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.setHeader("Allow", "GET, HEAD");
    return res.status(405).json({ error: "Method not allowed" });
  }

  const segments = req.query.path;
  if (!Array.isArray(segments) || segments.length === 0) {
    return res.status(400).json({ error: "Missing path" });
  }
  // Reject any segment that contains a separator or that traverses upward.
  // Next.js already URL-decodes segments, so a literal `..` or `/` here is
  // a real traversal attempt, not an encoding artifact.
  for (const seg of segments) {
    if (
      typeof seg !== "string" ||
      seg === "" ||
      seg === ".." ||
      seg === "." ||
      seg.includes("/") ||
      seg.includes("\\") ||
      seg.includes("\0")
    ) {
      return res.status(400).json({ error: "Invalid path" });
    }
  }

  let root: string;
  try {
    root = exportsRoot();
  } catch (e) {
    return res.status(500).json({ error: "Server misconfigured" });
  }

  const target = path.resolve(root, ...segments);
  // Resolved path must remain inside the exports root.
  if (target !== root && !target.startsWith(root + path.sep)) {
    return res.status(400).json({ error: "Invalid path" });
  }

  let stat;
  try {
    stat = await fs.promises.stat(target);
  } catch {
    return res.status(404).json({ error: "Not found" });
  }
  if (!stat.isFile()) {
    return res.status(404).json({ error: "Not found" });
  }

  const ext = path.extname(target).toLowerCase();
  const mime = MIME_TYPES[ext] ?? "application/octet-stream";
  const filename = path.basename(target);

  res.setHeader("Content-Type", mime);
  res.setHeader("Content-Length", stat.size.toString());
  res.setHeader(
    "Content-Disposition",
    `attachment; filename="${filename.replace(/"/g, "")}"`,
  );
  // Cache lightly: the export tree is rebuilt by load-db (typically nightly
  // on the server). `must-revalidate` so we always check size/mtime.
  res.setHeader("Cache-Control", "public, max-age=300, must-revalidate");
  res.setHeader("Last-Modified", stat.mtime.toUTCString());

  if (req.method === "HEAD") {
    return res.status(200).end();
  }

  return new Promise<void>((resolve, reject) => {
    const stream = fs.createReadStream(target);
    stream.on("error", (err) => {
      // Connection may already be partially written; best effort to close.
      try {
        res.destroy(err);
      } catch {
        // ignore
      }
      reject(err);
    });
    res.on("close", () => stream.destroy());
    stream.on("end", () => resolve());
    stream.pipe(res);
  });
}
