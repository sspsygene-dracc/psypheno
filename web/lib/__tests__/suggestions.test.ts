import { describe, it, expect, beforeAll } from "vitest";
import Database from "better-sqlite3";
import { fetchGeneSuggestions } from "@/lib/suggestions";
import { ALL_CONTROLS_SENTINEL_ID } from "@/lib/gene-query";

// Integration tests: hit the real DB at data/db/sspsygene.db. SSPSYGENE_DATA_DB
// is set in vitest.config.ts. Tests that need direct SQL access open a separate
// read-only handle so they don't disturb the module-level cache in db.ts.

function openReadonly(): Database.Database {
  const p = process.env.SSPSYGENE_DATA_DB;
  if (!p) throw new Error("SSPSYGENE_DATA_DB not set");
  return new Database(p, { readonly: true });
}

describe("fetchGeneSuggestions", () => {
  let directDb: Database.Database;
  beforeAll(() => {
    directDb = openReadonly();
  });

  it("returns [] for empty/whitespace input", () => {
    expect(fetchGeneSuggestions("")).toEqual([]);
    expect(fetchGeneSuggestions("   ")).toEqual([]);
  });

  it("strips embedded quotes from input", () => {
    // The two should produce equivalent results — quoting is normalized away.
    const a = fetchGeneSuggestions("BRCA");
    const b = fetchGeneSuggestions("'BRCA'");
    const c = fetchGeneSuggestions('"BRCA"');
    expect(a.map((s) => s.centralGeneId).sort()).toEqual(
      b.map((s) => s.centralGeneId).sort(),
    );
    expect(a.map((s) => s.centralGeneId).sort()).toEqual(
      c.map((s) => s.centralGeneId).sort(),
    );
  });

  it("matches human symbols by prefix", () => {
    const out = fetchGeneSuggestions("BRCA", 8);
    const symbols = out.map((s) => s.humanSymbol);
    expect(symbols).toContain("BRCA1");
    expect(symbols).toContain("BRCA2");
    // The first human-stage hits sort by num_datasets DESC, then symbol ASC,
    // so BRCA2 (14) precedes BRCA1 (13) in the result list.
    expect(symbols.indexOf("BRCA2")).toBeLessThan(symbols.indexOf("BRCA1"));
  });

  it("honors pageLimit", () => {
    const out = fetchGeneSuggestions("A", 3);
    expect(out.length).toBeLessThanOrEqual(3);
  });

  it("returns rows with the expected SearchSuggestion shape", () => {
    const out = fetchGeneSuggestions("BRCA1", 1);
    expect(out.length).toBeGreaterThan(0);
    const s = out[0];
    expect(typeof s.centralGeneId).toBe("number");
    expect(s.searchQuery).toBe("BRCA1");
    expect(typeof s.datasetCount).toBe("number");
    expect(["gene", "control"]).toContain(s.kind);
    if (s.mouseSymbols !== null) {
      expect(Array.isArray(s.mouseSymbols)).toBe(true);
    }
    if (s.humanSynonyms !== null) {
      expect(Array.isArray(s.humanSynonyms)).toBe(true);
    }
  });

  it("falls back to mouse-symbol matches when no human symbol matches", () => {
    // Find a mouse-only symbol present in extra_mouse_symbols whose central_gene
    // row has no human symbol that starts with the same prefix.
    const fixture = directDb
      .prepare(
        `SELECT ms.symbol AS symbol
         FROM extra_mouse_symbols ms
         WHERE ms.symbol IS NOT NULL AND length(ms.symbol) >= 4
           AND NOT EXISTS (
             SELECT 1 FROM central_gene cg
             WHERE cg.human_symbol IS NOT NULL
               AND cg.human_symbol LIKE substr(ms.symbol, 1, 4) || '%' COLLATE NOCASE
           )
         LIMIT 1`,
      )
      .get() as { symbol: string } | undefined;
    if (!fixture) {
      // No usable fixture in this DB — skip rather than fail. Real-world DBs
      // with full datasets will have plenty.
      return;
    }
    const prefix = fixture.symbol.slice(0, 4);
    const out = fetchGeneSuggestions(prefix, 8);
    expect(out.length).toBeGreaterThan(0);
    // At least one result should have this mouse symbol in its mouseSymbols list.
    const matched = out.find((s) =>
      (s.mouseSymbols ?? []).some(
        (m) => m.toLowerCase() === fixture.symbol.toLowerCase(),
      ),
    );
    expect(matched).toBeTruthy();
  });

  it("returns the synthetic ALL_CONTROLS suggestion for the 'control' keyword", () => {
    const out = fetchGeneSuggestions("control", 8);
    if (out.length === 0) return; // empty DB / no controls → tolerated
    const first = out[0];
    expect(first.centralGeneId).toBe(ALL_CONTROLS_SENTINEL_ID);
    expect(first.kind).toBe("control");
    expect(first.humanSymbol).toBe("CONTROL");
    // Subsequent entries (if any) should be real controls.
    for (const s of out.slice(1)) {
      expect(s.kind).toBe("control");
      expect(s.centralGeneId).toBeGreaterThan(0);
    }
  });

  it("treats 'controls' (plural) the same as 'control'", () => {
    const a = fetchGeneSuggestions("control", 8);
    const b = fetchGeneSuggestions("controls", 8);
    expect(a.map((s) => s.centralGeneId)).toEqual(
      b.map((s) => s.centralGeneId),
    );
  });

  it("'control' keyword is case-insensitive", () => {
    const a = fetchGeneSuggestions("control", 8);
    const b = fetchGeneSuggestions("CONTROL", 8);
    expect(a.map((s) => s.centralGeneId)).toEqual(
      b.map((s) => s.centralGeneId),
    );
  });

  it("direction-filtered results are a subset of the unfiltered results", () => {
    const all = new Set(
      fetchGeneSuggestions("BRCA", 20, null).map((s) => s.centralGeneId),
    );
    const target = fetchGeneSuggestions("BRCA", 20, "target");
    for (const s of target) {
      expect(all.has(s.centralGeneId)).toBe(true);
    }
  });

  it("re-uses cached prepared statements across calls without throwing", () => {
    const a = fetchGeneSuggestions("BRCA", 4);
    const b = fetchGeneSuggestions("BRCA", 4);
    expect(b.map((s) => s.centralGeneId)).toEqual(
      a.map((s) => s.centralGeneId),
    );
  });
});
