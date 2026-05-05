import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import Database from "better-sqlite3";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

function makeTmpDb(value: string): string {
  const p = path.join(
    os.tmpdir(),
    `sspsygene-test-${process.pid}-${Math.random().toString(36).slice(2)}.db`,
  );
  const db = new Database(p);
  db.exec("CREATE TABLE t (v TEXT)");
  db.prepare("INSERT INTO t (v) VALUES (?)").run(value);
  db.close();
  return p;
}

function readSentinel(dbPath: string): string {
  const db = new Database(dbPath, { readonly: true });
  const row = db.prepare("SELECT v FROM t LIMIT 1").get() as { v: string };
  db.close();
  return row.v;
}

describe("getDb", () => {
  const created: string[] = [];
  let target: string;

  beforeEach(() => {
    vi.resetModules();
    target = path.join(
      os.tmpdir(),
      `sspsygene-test-target-${process.pid}-${Math.random().toString(36).slice(2)}.db`,
    );
    created.push(target);
  });

  afterEach(() => {
    delete process.env.SSPSYGENE_DATA_DB;
    while (created.length) {
      const p = created.pop()!;
      try {
        fs.unlinkSync(p);
      } catch {
        /* ignore */
      }
    }
  });

  it("throws when SSPSYGENE_DATA_DB is unset", async () => {
    delete process.env.SSPSYGENE_DATA_DB;
    const { getDb } = await import("@/lib/db");
    expect(() => getDb()).toThrow(/SSPSYGENE_DATA_DB/);
  });

  it("opens the database read-only and returns a usable handle", async () => {
    const src = makeTmpDb("A");
    created.push(src);
    fs.copyFileSync(src, target);
    process.env.SSPSYGENE_DATA_DB = target;

    const { getDb } = await import("@/lib/db");
    const db = getDb();
    const row = db.prepare("SELECT v FROM t LIMIT 1").get() as { v: string };
    expect(row.v).toBe("A");
    expect(db.readonly).toBe(true);
  });

  it("returns the same instance when nothing changed", async () => {
    const src = makeTmpDb("A");
    created.push(src);
    fs.copyFileSync(src, target);
    process.env.SSPSYGENE_DATA_DB = target;

    const { getDb } = await import("@/lib/db");
    const a = getDb();
    const b = getDb();
    expect(a).toBe(b);
  });

  it("re-opens after an atomic rename swaps the inode", async () => {
    const srcA = makeTmpDb("A");
    const srcB = makeTmpDb("B");
    created.push(srcA, srcB);
    fs.copyFileSync(srcA, target);
    process.env.SSPSYGENE_DATA_DB = target;

    const { getDb } = await import("@/lib/db");
    const a = getDb();
    expect(
      (a.prepare("SELECT v FROM t LIMIT 1").get() as { v: string }).v,
    ).toBe("A");

    // Atomic rename — what `sspsygene load-db` does. Different inode.
    const inoBefore = fs.statSync(target).ino;
    fs.renameSync(srcB, target);
    created.splice(created.indexOf(srcB), 1);
    const inoAfter = fs.statSync(target).ino;
    expect(inoAfter).not.toBe(inoBefore);

    const b = getDb();
    expect(b).not.toBe(a);
    expect(
      (b.prepare("SELECT v FROM t LIMIT 1").get() as { v: string }).v,
    ).toBe("B");
  });

  it("smoke: confirm sentinel readback helper works", () => {
    const p = makeTmpDb("hello");
    created.push(p);
    expect(readSentinel(p)).toBe("hello");
  });
});
