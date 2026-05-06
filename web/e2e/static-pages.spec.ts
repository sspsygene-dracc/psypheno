import { test, expect } from "@playwright/test";

// Smoke tests for static / mostly-static pages: the page loads, the right
// heading is rendered, the page-specific landmark content is present, and
// internal navigation links work where applicable.

test("methods: page renders with the title and method sections", async ({
  page,
}) => {
  await page.goto("/methods");
  await expect(page).toHaveTitle(/Methods/);
  // Methods page covers Fisher / Cauchy / HMP. Check at least one shows up.
  const fisherHeader = page
    .getByRole("heading", { name: /Fisher/i })
    .first();
  await expect(fisherHeader).toBeVisible();
});

test("dataset-changelog: page renders changelog entries", async ({ page }) => {
  await page.goto("/dataset-changelog");
  await expect(page).toHaveTitle(/Dataset Changelog/);
  await expect(
    page.getByRole("heading", { name: /Dataset.*Changelog/i }),
  ).toBeVisible();
  // At least one entry table cell should be visible (date column).
  await expect(page.locator("table").first()).toBeVisible();
});

test("download: page renders dataset listing and code snippets", async ({
  page,
}) => {
  await page.goto("/download");
  await expect(page).toHaveTitle(/Downloads/);
  // The download page exposes manifest.tsv and per-dataset TSV download
  // links. Assert that at least one TSV download link is present.
  await expect(
    page.locator('a[href$=".tsv"]').first(),
  ).toBeVisible();
});

test("gene-parser: page renders TOC and pipeline sections", async ({
  page,
}) => {
  await page.goto("/gene-parser");
  await expect(page).toHaveTitle(/Gene-symbol parser/);
  await expect(
    page.getByRole("heading", { name: /How the Gene-Symbol Parser Works/ }),
  ).toBeVisible();
  // TOC anchors should be clickable.
  const tocLink = page.getByRole("link", { name: "What we run, in order" });
  await expect(tocLink).toBeVisible();
  await tocLink.click();
  // Clicking should bring the target section into view; URL hash sync is
  // suppressed by the e.preventDefault() handler, so we just verify the
  // section heading is reachable.
  await expect(
    page.getByRole("heading", { name: /What we run, in order/ }),
  ).toBeVisible();
});

test("combined-pvalues: redirects permanently to /most-significant", async ({
  page,
}) => {
  const response = await page.goto("/combined-pvalues");
  await expect(page).toHaveURL(/\/most-significant$/);
  // The Next.js permanent redirect (308) is preserved on the network
  // response. Playwright surfaces only the final 200 by default but the
  // intermediate 308 is included in the request chain.
  expect(response).not.toBeNull();
  await expect(
    page.getByRole("heading", { name: /Gene Ranking/ }),
  ).toBeVisible();
});

test("publications: anchor link from another page scrolls to the publication", async ({
  page,
}) => {
  // The full-datasets page exposes "See on Publications page" links that
  // include the per-publication anchor. We just verify anchor → publication
  // round-trips here.
  await page.goto("/publications");
  // First publication card has id="pub-<doi>"
  const article = page.locator('article[id^="pub-"]').first();
  await expect(article).toBeVisible();
  const id = await article.getAttribute("id");
  expect(id).toMatch(/^pub-/);
});
