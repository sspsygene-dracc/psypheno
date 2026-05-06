import { test, expect, type APIRequestContext } from "@playwright/test";

// Asserts the read-API cache policy from beb07c0: every successful 200
// response carries Cache-Control: public, max-age=60,
// stale-while-revalidate=60 (set via lib/cache-headers.ts).
//
// Worst-case post-rebuild staleness for an open tab is ~2 min — the
// wranglers are explicitly told this, so the contract is fixed. Any
// future change that drops one of the two directives (or the public
// scope) should fail this test loudly.

type Endpoint = {
  name: string;
  method: "GET" | "POST";
  path: string;
  body?: Record<string, unknown>;
};

// IDs picked to hit the success path of each handler. centralGeneId 2053
// is FOXG1, which exists in many SSPsyGene tables; the brain_organoid table
// is one of the largest, so paginated reads always return 200.
const FOXG1_CENTRAL_GENE_ID = 2053;
const SAMPLE_TABLE = "brain_organoid_atlas_nebula_gene_0_05_FDR";

const ENDPOINTS: Endpoint[] = [
  { name: "search-text", method: "GET", path: "/api/search-text?text=FOXG1" },
  { name: "all-genes", method: "GET", path: "/api/all-genes?page=1&pageSize=5" },
  { name: "full-datasets", method: "GET", path: "/api/full-datasets" },
  { name: "assay-types", method: "GET", path: "/api/assay-types" },
  {
    name: "dataset-data",
    method: "GET",
    path: `/api/dataset-data?tableName=${SAMPLE_TABLE}&page=1`,
  },
  { name: "dataset-changelog", method: "GET", path: "/api/dataset-changelog" },
  {
    name: "dataset-tables-with-pvalues",
    method: "GET",
    path: "/api/dataset-tables-with-pvalues",
  },
  { name: "publications", method: "GET", path: "/api/publications" },

  {
    name: "combined-pvalues",
    method: "POST",
    path: "/api/combined-pvalues",
    body: { centralGeneId: FOXG1_CENTRAL_GENE_ID },
  },
  {
    name: "combined-pvalues-table",
    method: "POST",
    path: "/api/combined-pvalues-table",
    body: {
      page: 1,
      pageSize: 10,
      method: "hmp",
      direction: "target",
      regulation: "any",
    },
  },
  {
    name: "significant-rows",
    method: "POST",
    path: "/api/significant-rows",
    body: {
      centralGeneId: FOXG1_CENTRAL_GENE_ID,
      filterBy: "pvalue",
      sortBy: "pvalue",
    },
  },
  {
    name: "dataset-significant-rows",
    method: "POST",
    path: "/api/dataset-significant-rows",
    body: {
      tableName: SAMPLE_TABLE,
      page: 1,
      pageSize: 10,
      filterBy: "pvalue",
      sortBy: "pvalue",
    },
  },
  {
    name: "gene-pair-data",
    method: "POST",
    path: "/api/gene-pair-data",
    body: {
      perturbedCentralGeneId: null,
      targetCentralGeneId: FOXG1_CENTRAL_GENE_ID,
    },
  },
  {
    name: "gene-pair-exists",
    method: "POST",
    path: "/api/gene-pair-exists",
    body: { perturbedSymbol: null, targetSymbol: "FOXG1" },
  },
  {
    name: "gene-table-page",
    method: "POST",
    path: "/api/gene-table-page",
    body: {
      tableName: SAMPLE_TABLE,
      page: 1,
      targetCentralGeneId: FOXG1_CENTRAL_GENE_ID,
    },
  },
  {
    name: "effect-distribution",
    method: "POST",
    path: "/api/effect-distribution",
    body: {
      tableName: SAMPLE_TABLE,
      targetCentralGeneId: FOXG1_CENTRAL_GENE_ID,
    },
  },
];

async function hit(request: APIRequestContext, ep: Endpoint) {
  if (ep.method === "GET") return request.get(ep.path);
  return request.post(ep.path, { data: ep.body ?? {} });
}

for (const ep of ENDPOINTS) {
  test(`cache-headers: ${ep.method} /api/${ep.name} sets max-age=60, stale-while-revalidate=60`, async ({
    request,
  }) => {
    const res = await hit(request, ep);
    expect(
      res.status(),
      `${ep.method} /api/${ep.name} should be 200 to assert headers`,
    ).toBe(200);
    const cc = res.headers()["cache-control"];
    expect(cc, `${ep.name} is missing a Cache-Control header`).toBeTruthy();
    expect(cc).toContain("max-age=60");
    expect(cc).toContain("stale-while-revalidate=60");
    expect(cc).toContain("public");
  });
}
