/**
 * Streams export bundles (per-table TSVs, metadata YAML, preprocessing YAML,
 * manifest, README, all-tables.zip) from the `export_files` table in the
 * SQLite DB. There is no `exports/` directory on the filesystem; the API
 * never opens a file by user-supplied path.
 *
 * The path comes from the URL (e.g. /api/download/tables/foo.tsv) and is
 * normalized into a single string ("tables/foo.tsv") that's used as the
 * BLOB lookup key.
 *
 * Special case: `/api/download/sspsygene.db` streams the SQLite DB file at
 * SSPSYGENE_DATA_DB directly (the DB can't store itself recursively). The
 * file path here is fixed by env, not by the URL.
 */
import type { NextApiRequest, NextApiResponse } from "next";
import fs from "fs";
import path from "path";
import { getDb } from "@/lib/db";

export const config = {
  api: { bodyParser: false, responseLimit: false },
};

type ExportRow = {
  content_type: string;
  content: Buffer;
  size: number;
  last_modified: number;
};

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
  // The blob key is the slash-joined path. Reject obviously-malformed
  // segments — even though we look up by exact equality (no FS walk), we
  // don't want odd characters reaching downstream consumers (e.g. the
  // Content-Disposition filename, where CR/LF would enable response
  // splitting).
  for (const seg of segments) {
    if (
      typeof seg !== "string" ||
      seg === "" ||
      seg.includes("/") ||
      seg.includes("\\") ||
      // eslint-disable-next-line no-control-regex
      /[\x00-\x1f\x7f]/.test(seg)
    ) {
      return res.status(400).json({ error: "Invalid path" });
    }
  }
  const blobPath = segments.join("/");

  // Special case: the SQLite DB itself can't be stored as a BLOB inside
  // itself, so stream it directly from the env-configured path. This is
  // the only filesystem read in this handler; the path is fixed by env,
  // not derived from the URL.
  if (blobPath === "sspsygene.db") {
    return streamDatabaseFile(req, res);
  }

  let row: ExportRow | undefined;
  try {
    row = getDb()
      .prepare(
        "SELECT content_type, content, size, last_modified FROM export_files WHERE path = ?",
      )
      .get(blobPath) as ExportRow | undefined;
  } catch (err) {
    // If the export_files table doesn't exist yet (DB rebuilt without
    // exports, or a partial build), respond 404 so the page degrades
    // gracefully instead of 500.
    console.error("download handler db error", err);
    return res.status(404).json({ error: "Not found" });
  }

  if (!row) {
    return res.status(404).json({ error: "Not found" });
  }

  // Distinguish per-table metadata.yaml from per-table preprocessing.yaml
  // in the saved filename — both URL paths end in `<tn>.yaml` and otherwise
  // collide in the user's downloads folder. Storage paths (and zip entries)
  // remain `metadata/<tn>.yaml` / `preprocessing/<tn>.yaml`; only the
  // Content-Disposition filename is rewritten.
  const lastSegment = segments[segments.length - 1] ?? blobPath;
  const filename =
    segments[0] === "preprocessing" && lastSegment.endsWith(".yaml")
      ? lastSegment.replace(/\.yaml$/, "_preprocessing.yaml")
      : lastSegment;
  const safeName = filename.replace(/"/g, "");

  res.setHeader("Content-Type", row.content_type);
  res.setHeader("Content-Length", String(row.size));
  res.setHeader("Content-Disposition", `attachment; filename="${safeName}"`);
  res.setHeader(
    "Last-Modified",
    new Date(row.last_modified * 1000).toUTCString(),
  );
  // Cache lightly: the export blobs are rebuilt by load-db (typically
  // nightly on the server). `must-revalidate` so we always check.
  res.setHeader("Cache-Control", "public, max-age=300, must-revalidate");

  if (req.method === "HEAD") {
    return res.status(200).end();
  }

  res.status(200).send(row.content);
}

async function streamDatabaseFile(
  req: NextApiRequest,
  res: NextApiResponse,
): Promise<void> {
  const dbPath = process.env.SSPSYGENE_DATA_DB;
  if (!dbPath) {
    res.status(500).json({ error: "Server misconfigured" });
    return;
  }
  const resolved = path.resolve(dbPath);

  let stat;
  try {
    stat = await fs.promises.stat(resolved);
  } catch {
    res.status(404).json({ error: "Not found" });
    return;
  }
  if (!stat.isFile()) {
    res.status(404).json({ error: "Not found" });
    return;
  }

  res.setHeader("Content-Type", "application/vnd.sqlite3");
  res.setHeader("Content-Length", String(stat.size));
  res.setHeader("Content-Disposition", 'attachment; filename="sspsygene.db"');
  res.setHeader("Last-Modified", stat.mtime.toUTCString());
  res.setHeader("Cache-Control", "public, max-age=300, must-revalidate");

  if (req.method === "HEAD") {
    res.status(200).end();
    return;
  }

  await new Promise<void>((resolve, reject) => {
    const stream = fs.createReadStream(resolved);
    stream.on("error", (err) => {
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
