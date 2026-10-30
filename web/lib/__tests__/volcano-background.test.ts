// @vitest-environment node
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import Database from "better-sqlite3";
import { effectCapFor, getVolcanoBackground } from "@/lib/volcano-background";

// genes 1–3 have one row each in per_gene; expt has 3 rows per gene.
function makeDb(): Database.Database {
  const db = new Database(":memory:");
  db.exec(`
    CREATE TABLE central_gene (id INTEGER PRIMARY KEY, human_symbol TEXT, mouse_symbols TEXT, kind TEXT);
    INSERT INTO central_gene VALUES (1,'A',NULL,'gene'),(2,'B',NULL,'gene'),(3,'C',NULL,'gene');
    CREATE TABLE data_tables (table_name TEXT, effect_column TEXT, pvalue_column TEXT, fdr_column TEXT,
                              display_columns TEXT, link_tables TEXT, field_labels TEXT);
    INSERT INTO data_tables VALUES
      ('per_gene','eff','p',NULL,'eff,p','g:per_gene__g:perturbed',NULL),
      ('expt','eff','p',NULL,'eff,p','g:expt__g:perturbed',NULL);
    CREATE TABLE per_gene (id INTEGER PRIMARY KEY, eff REAL, p REAL);
    CREATE TABLE per_gene__g (central_gene_id INTEGER, id INTEGER, PRIMARY KEY (central_gene_id, id));
    INSERT INTO per_gene VALUES (1,0.5,0.01),(2,NULL,NULL),(3,-1,0.2);
    INSERT INTO per_gene__g VALUES (1,1),(2,2),(3,3);
    CREATE TABLE expt (id INTEGER PRIMARY KEY, eff REAL, p REAL);
    CREATE TABLE expt__g (central_gene_id INTEGER, id INTEGER, PRIMARY KEY (central_gene_id, id));
  `);
  for (let id = 1; id <= 9; id++) {
    db.prepare("INSERT INTO expt VALUES (?, ?, 0.01)").run(id, id / 10);
    db.prepare("INSERT INTO expt__g VALUES (?, ?)").run(1 + ((id - 1) % 3), id);
  }
  return db;
}

describe("getVolcanoBackground", () => {
  let db: Database.Database;
  beforeEach(() => {
    db = makeDb();
  });
  afterEach(() => db.close());

  const points = (table: string, gene?: number) => {
    const r = getVolcanoBackground(db, table, gene);
    if (!r.ok) throw new Error(r.error);
    return r.background;
  };

  it("keeps the whole table for a gene in a one-row-per-gene table", () => {
    const whole = points("per_gene");
    expect(whole.perGeneTable).toBe(true);
    expect(whole.nNonNull).toBe(2);
    // Gene 2's row has no values: its background must not come back empty.
    expect(points("per_gene", 2)).toBe(whole);
    expect(points("per_gene", 1)).toBe(whole);
  });

  it("draws infinite effects at the largest finite value, flagged", () => {
    db.exec("INSERT INTO per_gene VALUES (4, 9e999, 0.03), (5, -9e999, 0.04)");
    db.exec("INSERT INTO per_gene__g VALUES (1,4),(2,5)");
    const pts = points("per_gene").volcanoPoints;
    expect(pts.filter((p) => !p.effectCapped)).toHaveLength(2);
    const capped = pts.filter((p) => p.effectCapped);
    expect(capped.map((p) => p.effect).sort()).toEqual([-1, 1]);
    expect(points("per_gene").nNonNull).toBe(4);
  });

  it("caps at 1 when a table has no finite effect", () => {
    db.exec("UPDATE expt SET eff = 9e999");
    expect(effectCapFor(db, "expt", "eff")).toBe(1);
  });

  it("restricts experiment tables to the perturbed gene's rows", () => {
    expect(points("expt").perGeneTable).toBe(false);
    expect(points("expt").nNonNull).toBe(9);
    expect(points("expt", 1).nNonNull).toBe(3);
  });
});
