import { test, expect, type APIRequestContext } from "@playwright/test";

// API smoke tests: hit each endpoint directly and verify the response
// shape, status code, and basic happy/edge-case behavior. These don't
// replace integration tests but catch the most obvious wire-format
// regressions.

async function getJson(request: APIRequestContext, path: string) {
  const res = await request.get(path);
  expect(res.status(), `${path} should be 200, got ${res.status()}`).toBe(200);
  return res.json();
}

test("api: GET /api/full-datasets returns datasets array", async ({
  request,
}) => {
  const data = await getJson(request, "/api/full-datasets");
  expect(Array.isArray(data.datasets)).toBe(true);
  expect(data.datasets.length).toBeGreaterThan(0);
  const first = data.datasets[0];
  expect(first).toHaveProperty("table_name");
});

test("api: GET /api/all-genes paginates with the requested page size", async ({
  request,
}) => {
  const data = await getJson(request, "/api/all-genes?page=1&pageSize=5");
  expect(data.genes.length).toBe(5);
  expect(data.page).toBe(1);
  expect(data.total).toBeGreaterThan(5);
  expect(data.totalPages).toBeGreaterThan(1);
});

test("api: GET /api/all-genes filters by search query", async ({ request }) => {
  const data = await getJson(
    request,
    "/api/all-genes?page=1&pageSize=10&q=BDNF",
  );
  expect(data.total).toBeGreaterThanOrEqual(1);
  // Every returned gene should have BDNF in its symbol or synonyms (case-insensitive).
  const matches = data.genes.some((g: { humanSymbol?: string }) =>
    (g.humanSymbol ?? "").toUpperCase().includes("BDNF"),
  );
  expect(matches).toBe(true);
});

test("api: GET /api/all-genes returns empty for nonsense query", async ({
  request,
}) => {
  const data = await getJson(
    request,
    "/api/all-genes?page=1&pageSize=10&q=zzNoSuchGenezz",
  );
  expect(data.total).toBe(0);
  expect(data.genes.length).toBe(0);
});

test("api: GET /api/search-text returns suggestions for a real symbol", async ({
  request,
}) => {
  const res = await request.get("/api/search-text?text=FOXG1");
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(Array.isArray(body.suggestions)).toBe(true);
  expect(body.suggestions.length).toBeGreaterThan(0);
});

test("api: POST /api/search-text rejects with 405", async ({ request }) => {
  const res = await request.post("/api/search-text", {
    data: { text: "FOXG1" },
  });
  expect(res.status()).toBe(405);
});

test("api: GET /api/search-text empty text returns empty suggestions", async ({
  request,
}) => {
  const res = await request.get("/api/search-text?text=");
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.suggestions).toEqual([]);
});

test("api: GET /api/search-text missing text returns 400", async ({
  request,
}) => {
  const res = await request.get("/api/search-text");
  expect(res.status()).toBe(400);
});

test("api: GET /api/publications returns publications array", async ({
  request,
}) => {
  const data = await getJson(request, "/api/publications");
  expect(Array.isArray(data.publications)).toBe(true);
  expect(data.publications.length).toBeGreaterThan(0);
  const first = data.publications[0];
  expect(first).toHaveProperty("doi");
  expect(first).toHaveProperty("authors");
});

test("api: GET /api/dataset-changelog returns entries", async ({ request }) => {
  const data = await getJson(request, "/api/dataset-changelog");
  expect(Array.isArray(data.entries)).toBe(true);
  expect(data.entries.length).toBeGreaterThan(0);
});

test("api: GET /api/assay-types returns label map", async ({ request }) => {
  const data = await getJson(request, "/api/assay-types");
  expect(typeof data.assayTypes).toBe("object");
  // assayTypes is keyed by assay key — at least one entry.
  expect(Object.keys(data.assayTypes).length).toBeGreaterThan(0);
});

test("api: GET /api/dataset-tables-with-pvalues returns tables and labels", async ({
  request,
}) => {
  const data = await getJson(request, "/api/dataset-tables-with-pvalues");
  expect(Array.isArray(data.tables)).toBe(true);
  expect(data.tables.length).toBeGreaterThan(0);
  expect(typeof data.assayTypeLabels).toBe("object");
});

test("api: GET /api/dataset-data with valid tableName returns rows", async ({
  request,
}) => {
  // Use a known table name from the brain organoid atlas.
  const data = await getJson(
    request,
    "/api/dataset-data?tableName=brain_organoid_atlas_nebula_gene_0_05_FDR&page=1",
  );
  expect(Array.isArray(data.rows)).toBe(true);
  expect(data.rows.length).toBeGreaterThan(0);
  expect(data.tableName).toBe("brain_organoid_atlas_nebula_gene_0_05_FDR");
  expect(Array.isArray(data.displayColumns)).toBe(true);
});

test("api: GET /api/dataset-data with bad tableName returns 4xx", async ({
  request,
}) => {
  const res = await request.get(
    "/api/dataset-data?tableName=zz_no_such_table_zz",
  );
  expect(res.status()).toBeGreaterThanOrEqual(400);
});

test("api: GET /api/dataset-data with column filter narrows totalRows", async ({
  request,
}) => {
  const baseline = await getJson(
    request,
    "/api/dataset-data?tableName=brain_organoid_atlas_nebula_gene_0_05_FDR&page=1",
  );
  const filtered = await getJson(
    request,
    "/api/dataset-data?tableName=brain_organoid_atlas_nebula_gene_0_05_FDR&page=1&filters=" +
      encodeURIComponent('{"pvalue":"<0.001"}'),
  );
  expect(filtered.totalRows).toBeLessThan(baseline.totalRows);
});

test("api: POST /api/combined-pvalues-table returns ranked rows", async ({
  request,
}) => {
  const res = await request.post("/api/combined-pvalues-table", {
    data: {
      page: 1,
      pageSize: 10,
      method: "hmp",
      direction: "target",
      regulation: "any",
    },
  });
  expect(res.status()).toBe(200);
  const data = await res.json();
  expect(Array.isArray(data.rows)).toBe(true);
});

test("api: POST /api/gene-pair-data with no genes returns no results", async ({
  request,
}) => {
  const res = await request.post("/api/gene-pair-data", {
    data: { perturbedCentralGeneId: null, targetCentralGeneId: null },
  });
  expect(res.status()).toBeGreaterThanOrEqual(200);
});
