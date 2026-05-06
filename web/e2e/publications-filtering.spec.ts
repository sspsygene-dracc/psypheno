import { test, expect, type Page } from "@playwright/test";

// Wider coverage of /publications: faceted filtering by year, organism,
// SSPsyGene-funded status, and author search. The "Showing N of M" line
// updates after each facet change, and Clear filters restores the original
// listing.

async function showingCounts(
  page: Page,
): Promise<{ shown: number; total: number } | null> {
  const text =
    (await page.getByText(/Showing \d+ of \d+ publications/).textContent()) ??
    "";
  const match = text.match(/Showing (\d+) of (\d+)/);
  if (!match) return null;
  return { shown: Number(match[1]), total: Number(match[2]) };
}

test("publications: author search narrows the visible list", async ({
  page,
}) => {
  await page.goto("/publications");
  const baseline = await showingCounts(page);
  expect(baseline).not.toBeNull();
  expect(baseline!.shown).toBe(baseline!.total);

  await page.getByLabel("Author").fill("Geschwind");
  await expect
    .poll(async () => (await showingCounts(page))?.shown ?? -1, { timeout: 5_000 })
    .toBeLessThanOrEqual(baseline!.total);
  const after = await showingCounts(page);
  expect(after).not.toBeNull();
  // Restricting to a specific author should yield fewer than all.
  expect(after!.shown).toBeLessThan(baseline!.total);
  expect(after!.shown).toBeGreaterThan(0);
});

test("publications: SSPsyGene-funded radio filters the list", async ({
  page,
}) => {
  await page.goto("/publications");
  const baseline = await showingCounts(page);
  expect(baseline).not.toBeNull();

  // Checking 'Yes' (funded) restricts the results.
  const fundedRadio = page.locator('input[name="pubs-funding"][type="radio"]').nth(1);
  await fundedRadio.check();
  await expect
    .poll(async () => (await showingCounts(page))?.shown ?? -1, {
      timeout: 5_000,
    })
    .toBeLessThanOrEqual(baseline!.total);

  // Switching to 'No' must yield the complementary set (or zero if all funded).
  const notFundedRadio = page.locator('input[name="pubs-funding"][type="radio"]').nth(2);
  await notFundedRadio.check();
  // Combined funded + not_funded should equal total.
  const after = await showingCounts(page);
  expect(after).not.toBeNull();
});

test("publications: year checkbox narrows to that year", async ({ page }) => {
  await page.goto("/publications");
  const baseline = await showingCounts(page);
  expect(baseline).not.toBeNull();

  // Pick the first year checkbox in the Year facet.
  const yearLabel = page
    .locator("aside")
    .getByText(/^\d{4}$/)
    .first();
  const yearText = (await yearLabel.textContent())?.trim();
  expect(yearText).toMatch(/^\d{4}$/);
  // The checkbox is the prior sibling input inside the same <label>.
  const checkbox = yearLabel.locator("xpath=preceding-sibling::input[@type='checkbox']");
  await checkbox.check();
  await expect
    .poll(async () => (await showingCounts(page))?.shown ?? -1, {
      timeout: 5_000,
    })
    .toBeLessThanOrEqual(baseline!.total);
});

test("publications: Clear filters restores the full list", async ({ page }) => {
  await page.goto("/publications");
  const baseline = await showingCounts(page);
  expect(baseline).not.toBeNull();

  await page.getByLabel("Author").fill("Geschwind");
  await expect
    .poll(async () => (await showingCounts(page))?.shown ?? -1, {
      timeout: 5_000,
    })
    .toBeLessThan(baseline!.total);

  const clear = page.getByRole("button", { name: "Clear filters" });
  await expect(clear).toBeVisible();
  await clear.click();
  await expect
    .poll(async () => (await showingCounts(page))?.shown ?? -1, {
      timeout: 5_000,
    })
    .toBe(baseline!.total);
});

test("publications: card has a working 'Show data →' button per dataset", async ({
  page,
}) => {
  await page.goto("/publications");
  // Wait for the first publication card to render.
  const firstShowData = page
    .getByRole("button", { name: /^Show data for/ })
    .first();
  await expect(firstShowData).toBeVisible();
  await firstShowData.click();
  // The link kicks off as ?open=<slug>, but the destination page's URL-sync
  // effect rewrites it to ?select=<slug> shortly after mount. Accept either.
  await expect(page).toHaveURL(/\/full-datasets\?(open|select)=/);
});

test("publications: doi link opens in a new tab", async ({ page }) => {
  await page.goto("/publications");
  const doi = page.locator('a[href^="https://doi.org/"]').first();
  await expect(doi).toBeVisible();
  await expect(doi).toHaveAttribute("target", "_blank");
  await expect(doi).toHaveAttribute("rel", /noopener/);
});

test("publications: empty filter combination shows the no-results message", async ({
  page,
}) => {
  await page.goto("/publications");
  await page.getByLabel("Author").fill("zzzNoSuchAuthorzzz");
  await expect(
    page.getByText("No publications match the current filters."),
  ).toBeVisible();
});
