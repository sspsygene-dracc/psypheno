// @vitest-environment node
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import Database from "better-sqlite3";
import { getOrthologNotes, parseCandidateOrthologs } from "@/lib/orthologs";
import { urlSymbol, type SearchSuggestion } from "@/state/SearchSuggestion";

// Mouse Adh1 (id 10) is mouse-only with candidates ADH1A (1, in the DB),
// ADH1B (2, in the DB) and ADH1C (3, not in the DB: no dataset uses it).
const ADH1 = JSON.stringify([
  { hgnc_id: "HGNC:249", symbol: "ADH1A", central_gene_id: 1 },
  { hgnc_id: "HGNC:250", symbol: "ADH1B", central_gene_id: 2 },
  { hgnc_id: "HGNC:251", symbol: "ADH1C", central_gene_id: 3 },
]);

function makeDb(): Database.Database {
  const db = new Database(":memory:");
  db.exec(`
    CREATE TABLE central_gene (id INTEGER PRIMARY KEY, human_symbol TEXT, hgnc_id TEXT,
                               mouse_symbols TEXT, candidate_human_orthologs TEXT);
    INSERT INTO central_gene VALUES
      (1, 'ADH1A', 'HGNC:249', NULL, NULL),
      (2, 'ADH1B', 'HGNC:250', 'Adh7', NULL),
      (5, 'TP53', 'HGNC:11998', 'Trp53', NULL);
  `);
  db.prepare("INSERT INTO central_gene VALUES (10, NULL, NULL, 'Adh1', ?)").run(ADH1);
  return db;
}

describe("parseCandidateOrthologs", () => {
  it("parses the stored JSON", () => {
    expect(parseCandidateOrthologs(ADH1).map((c) => c.symbol)).toEqual([
      "ADH1A",
      "ADH1B",
      "ADH1C",
    ]);
  });
  it("tolerates null and junk", () => {
    expect(parseCandidateOrthologs(null)).toEqual([]);
    expect(parseCandidateOrthologs("not json")).toEqual([]);
    expect(parseCandidateOrthologs('{"a":1}')).toEqual([]);
    expect(parseCandidateOrthologs('[{"symbol":1}]')).toEqual([]);
  });
});

describe("getOrthologNotes", () => {
  let db: Database.Database;
  beforeEach(() => {
    db = makeDb();
  });
  afterEach(() => db.close());

  it("lists a mouse-only gene's candidates, unlinking those not in the DB", () => {
    const notes = getOrthologNotes(db, 10);
    expect(notes.candidateOf).toEqual([]);
    expect(notes.candidates).toEqual([
      { hgncId: "HGNC:249", symbol: "ADH1A", centralGeneId: 1 },
      { hgncId: "HGNC:250", symbol: "ADH1B", centralGeneId: 2 },
      { hgncId: "HGNC:251", symbol: "ADH1C", centralGeneId: null },
    ]);
  });

  it("gives a human candidate the reverse note", () => {
    expect(getOrthologNotes(db, 1)).toEqual({
      candidates: [],
      candidateOf: [{ centralGeneId: 10, mouseSymbol: "Adh1" }],
    });
  });

  it("is empty for an ordinary gene and an unknown id", () => {
    expect(getOrthologNotes(db, 5)).toEqual({ candidates: [], candidateOf: [] });
    expect(getOrthologNotes(db, 999)).toEqual({ candidates: [], candidateOf: [] });
  });

  it("copes with a DB built before the column existed", () => {
    const old = new Database(":memory:");
    old.exec("CREATE TABLE central_gene (id INTEGER PRIMARY KEY, human_symbol TEXT, hgnc_id TEXT)");
    expect(getOrthologNotes(old, 1)).toEqual({ candidates: [], candidateOf: [] });
    old.close();
  });
});

describe("urlSymbol", () => {
  const base: SearchSuggestion = {
    centralGeneId: 1,
    searchQuery: "x",
    displayLabel: null,
    humanSymbol: null,
    mouseSymbols: null,
    humanSynonyms: null,
    mouseSynonyms: null,
    datasetCount: 1,
    kind: "gene",
  };
  it("prefers the human symbol, else the first mouse symbol", () => {
    expect(urlSymbol({ ...base, humanSymbol: "ADH1A", mouseSymbols: ["Adh1a"] })).toBe("ADH1A");
    expect(urlSymbol({ ...base, mouseSymbols: ["Adh1"] })).toBe("Adh1");
    expect(urlSymbol(base)).toBeNull();
    expect(urlSymbol(null)).toBeNull();
  });
});
