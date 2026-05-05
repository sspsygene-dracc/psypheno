import { describe, it, expect } from "vitest";
import {
  ALL_CONTROLS_SENTINEL_ID,
  buildFilterClause,
  buildGeneQuery,
  buildOrderByClause,
  parseDisplayColumns,
  parseLinkTablesForDirection,
  parseSourceColumnsForDirection,
  pickDefaultSortColumn,
  sanitizeIdentifier,
  validateSortColumn,
} from "@/lib/gene-query";

describe("sanitizeIdentifier", () => {
  it("accepts word characters", () => {
    expect(sanitizeIdentifier("foo_bar1")).toBe("foo_bar1");
  });

  it("rejects empty string", () => {
    expect(() => sanitizeIdentifier("")).toThrow(/Invalid identifier/);
  });

  it("rejects SQL-injection-y values", () => {
    expect(() => sanitizeIdentifier("foo;DROP TABLE x")).toThrow(
      /Invalid identifier/,
    );
  });

  it("rejects hyphens and spaces", () => {
    expect(() => sanitizeIdentifier("a-b")).toThrow();
    expect(() => sanitizeIdentifier("a b")).toThrow();
  });
});

describe("validateSortColumn", () => {
  it("returns null for missing input", () => {
    expect(validateSortColumn(null, ["a", "b"])).toBeNull();
    expect(validateSortColumn(undefined, ["a", "b"])).toBeNull();
    expect(validateSortColumn("", ["a", "b"])).toBeNull();
  });

  it("returns null when the column is not in the allowlist", () => {
    expect(validateSortColumn("c", ["a", "b"])).toBeNull();
  });

  it("returns the sanitized column when allowed", () => {
    expect(validateSortColumn("foo_bar", ["foo_bar", "x"])).toBe("foo_bar");
  });
});

describe("pickDefaultSortColumn", () => {
  it("prefers fdr_column over pvalue_column", () => {
    expect(
      pickDefaultSortColumn({ fdr_column: "fdr", pvalue_column: "pv" }),
    ).toBe("fdr");
  });

  it("falls back to pvalue_column when fdr is null", () => {
    expect(
      pickDefaultSortColumn({ fdr_column: null, pvalue_column: "pv" }),
    ).toBe("pv");
  });

  it("returns null when both are null", () => {
    expect(
      pickDefaultSortColumn({ fdr_column: null, pvalue_column: null }),
    ).toBeNull();
  });

  it("returns the first comma-split entry, trimmed", () => {
    expect(
      pickDefaultSortColumn({
        fdr_column: " fdr_a , fdr_b ",
        pvalue_column: null,
      }),
    ).toBe("fdr_a");
  });
});

describe("buildOrderByClause", () => {
  it("returns empty string for null spec", () => {
    expect(buildOrderByClause(null)).toBe("");
  });

  it("builds asc clause with NULLS LAST", () => {
    expect(buildOrderByClause({ column: "x", mode: "asc" })).toBe(
      "ORDER BY x ASC NULLS LAST",
    );
  });

  it("builds desc clause with NULLS FIRST", () => {
    expect(buildOrderByClause({ column: "x", mode: "desc" })).toBe(
      "ORDER BY x DESC NULLS FIRST",
    );
  });

  it("wraps in ABS() for asc_abs/desc_abs", () => {
    expect(buildOrderByClause({ column: "lfc", mode: "asc_abs" })).toBe(
      "ORDER BY ABS(lfc) ASC NULLS LAST",
    );
    expect(buildOrderByClause({ column: "lfc", mode: "desc_abs" })).toBe(
      "ORDER BY ABS(lfc) DESC NULLS FIRST",
    );
  });

  it("applies tableAlias prefix", () => {
    expect(
      buildOrderByClause({ column: "x", mode: "asc", tableAlias: "b" }),
    ).toBe("ORDER BY b.x ASC NULLS LAST");
    expect(
      buildOrderByClause({ column: "x", mode: "desc_abs", tableAlias: "b" }),
    ).toBe("ORDER BY ABS(b.x) DESC NULLS FIRST");
  });
});

describe("parseDisplayColumns", () => {
  it("returns [] for empty/whitespace", () => {
    expect(parseDisplayColumns("")).toEqual([]);
    expect(parseDisplayColumns("   ")).toEqual([]);
  });

  it("splits, trims, sanitizes", () => {
    expect(parseDisplayColumns(" a , b_2 , c ")).toEqual(["a", "b_2", "c"]);
  });

  it("throws when an entry contains an illegal character", () => {
    expect(() => parseDisplayColumns("a, b-c")).toThrow();
  });
});

describe("parseLinkTablesForDirection", () => {
  it("returns [] for empty/null input", () => {
    expect(parseLinkTablesForDirection("", "perturbed")).toEqual([]);
  });

  it("filters by direction", () => {
    const raw = "col1:lt_a:perturbed,col2:lt_b:target,col3:lt_c:perturbed";
    expect(parseLinkTablesForDirection(raw, "perturbed")).toEqual([
      "lt_a",
      "lt_c",
    ]);
    expect(parseLinkTablesForDirection(raw, "target")).toEqual(["lt_b"]);
  });

  it("drops entries that lack a direction segment", () => {
    expect(parseLinkTablesForDirection("col:lt_only", "perturbed")).toEqual([]);
    // A single-segment entry has no name and no direction.
    expect(parseLinkTablesForDirection("solo", "perturbed")).toEqual([]);
  });

  it("trims whitespace around comma-separated entries", () => {
    expect(
      parseLinkTablesForDirection(" col:lt_a:perturbed , col:lt_b:target ", "target"),
    ).toEqual(["lt_b"]);
  });
});

describe("parseSourceColumnsForDirection", () => {
  it("normalizes column names (toSqlFriendlyColumn)", () => {
    expect(
      parseSourceColumnsForDirection("Gene-Symbol:lt_x:target", "target"),
    ).toEqual(["gene_symbol"]);
  });

  it("filters by direction", () => {
    const raw = "ColA:lt_a:perturbed,ColB:lt_b:target";
    expect(parseSourceColumnsForDirection(raw, "perturbed")).toEqual(["cola"]);
    expect(parseSourceColumnsForDirection(raw, "target")).toEqual(["colb"]);
  });

  it("returns [] for empty input", () => {
    expect(parseSourceColumnsForDirection("", "target")).toEqual([]);
  });
});

describe("buildFilterClause", () => {
  const displayColumns = ["pvalue", "log2fc", "gene_symbol"];
  const scalarColumns = new Set(["pvalue", "log2fc"]);

  it("returns empty for null/undefined/empty filters", () => {
    expect(
      buildFilterClause({ filters: null, displayColumns, scalarColumns }),
    ).toEqual({ clause: "", params: [] });
    expect(
      buildFilterClause({ filters: undefined, displayColumns, scalarColumns }),
    ).toEqual({ clause: "", params: [] });
    expect(
      buildFilterClause({ filters: {}, displayColumns, scalarColumns }),
    ).toEqual({ clause: "", params: [] });
  });

  it("parses scalar with operator (>=, <, !=)", () => {
    const r = buildFilterClause({
      filters: { pvalue: ">= 0.05", log2fc: "<2", gene_symbol: "!= BRCA1" },
      displayColumns,
      scalarColumns,
    });
    expect(r.clause).toContain("pvalue >= ?");
    expect(r.clause).toContain("log2fc < ?");
    expect(r.params).toContain(0.05);
    expect(r.params).toContain(2);
    // gene_symbol is non-scalar, so '!=' is not parsed as operator — substring.
    expect(r.clause).toContain("gene_symbol LIKE ?");
  });

  it("translates '=' to SQL '='", () => {
    const r = buildFilterClause({
      filters: { pvalue: "= 0.5" },
      displayColumns,
      scalarColumns,
    });
    expect(r.clause).toContain("pvalue = ?");
    expect(r.params).toEqual([0.5]);
  });

  it("falls back to substring match when scalar value has no operator", () => {
    const r = buildFilterClause({
      filters: { pvalue: "1.2" },
      displayColumns,
      scalarColumns,
    });
    expect(r.clause).toContain("CAST(pvalue AS TEXT) LIKE ? ESCAPE '\\'");
    expect(r.params).toEqual(["%1.2%"]);
  });

  it("accepts scientific notation", () => {
    const r = buildFilterClause({
      filters: { pvalue: "<1e-3" },
      displayColumns,
      scalarColumns,
    });
    expect(r.clause).toContain("pvalue < ?");
    expect(r.params).toEqual([1e-3]);
  });

  it("accepts leading-dot fractions", () => {
    const r = buildFilterClause({
      filters: { pvalue: "<.03" },
      displayColumns,
      scalarColumns,
    });
    expect(r.clause).toContain("pvalue < ?");
    expect(r.params).toEqual([0.03]);
  });

  it("escapes LIKE wildcards in non-scalar values", () => {
    const r = buildFilterClause({
      filters: { gene_symbol: "BR_C%A" },
      displayColumns,
      scalarColumns,
    });
    expect(r.clause).toContain("gene_symbol LIKE ? ESCAPE '\\' COLLATE NOCASE");
    expect(r.params).toEqual(["%BR\\_C\\%A%"]);
  });

  it("drops columns not in displayColumns", () => {
    const r = buildFilterClause({
      filters: { not_a_column: "x" },
      displayColumns,
      scalarColumns,
    });
    expect(r).toEqual({ clause: "", params: [] });
  });

  it("drops empty/whitespace values", () => {
    const r = buildFilterClause({
      filters: { pvalue: "   ", gene_symbol: "" },
      displayColumns,
      scalarColumns,
    });
    expect(r).toEqual({ clause: "", params: [] });
  });

  it("applies tableAlias prefix", () => {
    const r = buildFilterClause({
      filters: { pvalue: ">0.5" },
      displayColumns,
      scalarColumns,
      tableAlias: "b",
    });
    expect(r.clause).toContain("b.pvalue > ?");
  });
});

describe("buildGeneQuery", () => {
  const baseTable = "demo_table";
  const displayCols = ["x", "y"];

  it("returns null when no central gene IDs are provided", () => {
    expect(
      buildGeneQuery({
        baseTable,
        displayCols,
        linkTablesRaw: "col:lt:perturbed",
      }),
    ).toBeNull();
  });

  it("returns null when perturbed direction has zero or multiple link tables", () => {
    expect(
      buildGeneQuery({
        baseTable,
        displayCols,
        linkTablesRaw: "",
        perturbedCentralGeneId: 7,
      }),
    ).toBeNull();
    expect(
      buildGeneQuery({
        baseTable,
        displayCols,
        linkTablesRaw: "c:lt_a:perturbed,c:lt_b:perturbed",
        perturbedCentralGeneId: 7,
      }),
    ).toBeNull();
  });

  it("builds a single-direction subquery", () => {
    const q = buildGeneQuery({
      baseTable,
      displayCols,
      linkTablesRaw: "col:lt_p:perturbed",
      perturbedCentralGeneId: 42,
    });
    expect(q).not.toBeNull();
    expect(q!.selectCols).toBe("b.x, b.y");
    expect(q!.fromAndWhere).toBe(
      "FROM demo_table b WHERE b.id IN (SELECT id FROM lt_p WHERE central_gene_id = ?)",
    );
    expect(q!.params).toEqual(["42"]);
  });

  it("INTERSECTs both directions when both IDs are set", () => {
    const q = buildGeneQuery({
      baseTable,
      displayCols,
      linkTablesRaw: "c1:lt_p:perturbed,c2:lt_t:target",
      perturbedCentralGeneId: 1,
      targetCentralGeneId: 2,
    });
    expect(q).not.toBeNull();
    expect(q!.fromAndWhere).toContain("INTERSECT");
    expect(q!.fromAndWhere).toContain("FROM lt_p");
    expect(q!.fromAndWhere).toContain("FROM lt_t");
    expect(q!.params).toEqual(["1", "2"]);
  });

  it("expands ALL_CONTROLS sentinel into a kind='control' subquery", () => {
    const q = buildGeneQuery({
      baseTable,
      displayCols,
      linkTablesRaw: "col:lt_p:perturbed",
      perturbedCentralGeneId: ALL_CONTROLS_SENTINEL_ID,
    });
    expect(q).not.toBeNull();
    expect(q!.fromAndWhere).toContain("FROM central_gene WHERE kind = 'control'");
    // Sentinel path doesn't bind the id as a parameter.
    expect(q!.params).toEqual([]);
  });
});
