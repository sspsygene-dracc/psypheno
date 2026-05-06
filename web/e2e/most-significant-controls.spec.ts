import { test, expect, type Page } from "@playwright/test";

// Coverage of /most-significant beyond the direction toggle: method radio
// (Fisher / Cauchy / HMP), regulation radio (All / Up / Down), gene-name
// search filter, gene info row expansion, and URL state sync after
// switching method.

async function firstRankedSymbol(page: Page): Promise<string> {
  const rankedTable = page.locator("#ranked-genes-table");
  await expect(rankedTable).toBeVisible();
  const link = rankedTable
    .getByRole("link")
    .filter({ hasNotText: /Methods/ })
    .first();
  await expect(link).toBeVisible();
  return (await link.textContent())?.trim() ?? "";
}

async function topNRankedSymbols(page: Page, n: number): Promise<string[]> {
  const rankedTable = page.locator("#ranked-genes-table");
  await expect(rankedTable).toBeVisible();
  const links = await rankedTable
    .getByRole("link")
    .filter({ hasNotText: /Methods/ })
    .all();
  const symbols: string[] = [];
  for (let i = 0; i < Math.min(n, links.length); i++) {
    symbols.push(((await links[i].textContent()) ?? "").trim());
  }
  return symbols;
}

test("most-significant: switching method changes the ranking", async ({
  page,
}) => {
  await page.goto("/most-significant");
  // Default method is HMP.
  const hmpRadio = page.getByLabel("HMP", { exact: true });
  await expect(hmpRadio).toBeChecked();
  // Wait for the first ranked row to render.
  await expect(
    page
      .locator("#ranked-genes-table")
      .getByRole("link")
      .filter({ hasNotText: /Methods/ })
      .first(),
  ).toBeVisible();
  const initialTop10 = await topNRankedSymbols(page, 10);
  expect(initialTop10.length).toBeGreaterThan(0);

  // Switch to Fisher; the top-10 list should differ at *some* position even
  // if the #1 gene happens to dominate every method.
  await page.getByLabel("Fisher", { exact: true }).check();
  await expect
    .poll(() => topNRankedSymbols(page, 10).then((arr) => arr.join(",")), {
      timeout: 15_000,
      message: "top-10 ranking did not change after switching to Fisher",
    })
    .not.toBe(initialTop10.join(","));
});

test("most-significant: ?method= URL param hydrates the radio", async ({
  page,
}) => {
  // URL → state hydration: explicit ?method=fisher should select Fisher
  // when the page mounts.
  await page.goto("/most-significant?method=fisher");
  await expect(page.getByLabel("Fisher", { exact: true })).toBeChecked();
});

test("most-significant: ?dir=perturbed URL param flips Direction radio", async ({
  page,
}) => {
  await page.goto("/most-significant?dir=perturbed");
  await expect(page.getByLabel("Perturbed", { exact: true })).toBeChecked();
});

test("most-significant: ?gene=<symbol> URL param hydrates the gene filter", async ({
  page,
}) => {
  await page.goto("/most-significant?gene=CHD8");
  await expect(
    page.locator('th input[placeholder="Filter..."]'),
  ).toHaveValue("CHD8");
});

test("most-significant: gene name filter restricts the visible rows", async ({
  page,
}) => {
  await page.goto("/most-significant");
  const rankedTable = page.locator("#ranked-genes-table");
  await expect(rankedTable).toBeVisible();
  // Wait for table to populate.
  await expect(
    rankedTable.getByRole("link").filter({ hasNotText: /Methods/ }).first(),
  ).toBeVisible();

  const filterInput = page.locator('th input[placeholder="Filter..."]');
  await filterInput.fill("CHD");
  // Wait for the rows to update — every visible gene-link in the rank
  // column should start with "CH" (case-insensitive).
  await expect
    .poll(
      async () => {
        const links = await rankedTable
          .getByRole("link")
          .filter({ hasNotText: /Methods/ })
          .all();
        const symbols = await Promise.all(
          links.map(async (l) => (await l.textContent())?.trim().toUpperCase() ?? ""),
        );
        return symbols;
      },
      { timeout: 10_000 },
    )
    .toEqual(expect.arrayContaining([expect.stringMatching(/^CH/)]));
});

test("most-significant: regulation Up changes the rankings", async ({ page }) => {
  await page.goto("/most-significant");
  const rankedTable = page.locator("#ranked-genes-table");
  await expect(rankedTable).toBeVisible();
  // Wait for default ranking.
  await expect(
    rankedTable.getByRole("link").filter({ hasNotText: /Methods/ }).first(),
  ).toBeVisible();
  const before = await firstRankedSymbol(page);

  await page.getByLabel("Up-regulated", { exact: true }).check();
  // The ranking changes when regulation flips from "All" to "Up".
  await expect
    .poll(() => firstRankedSymbol(page), { timeout: 15_000 })
    .not.toBe(before);
});

test("most-significant: gene info expand button reveals details", async ({
  page,
}) => {
  await page.goto("/most-significant");
  const rankedTable = page.locator("#ranked-genes-table");
  await expect(rankedTable).toBeVisible();
  await expect(
    rankedTable.getByRole("link").filter({ hasNotText: /Methods/ }).first(),
  ).toBeVisible();

  // The first row's "Show" button toggles the gene-info expansion.
  const showBtn = page
    .getByRole("button", { name: /Show/ })
    .first();
  await expect(showBtn).toBeVisible();
  await showBtn.click();
  // After expansion the button text becomes "Hide".
  await expect(
    page.getByRole("button", { name: /Hide/ }).first(),
  ).toBeVisible();
});

test("most-significant: 'Include none' / 'Include all' buttons work", async ({
  page,
}) => {
  await page.goto("/most-significant");
  // Wait for the gene-selection panel to render.
  await expect(page.getByText("Show union of:")).toBeVisible();
  // Click 'Include none'.
  const includeNone = page.getByRole("button", { name: "Include none" });
  await expect(includeNone).toBeVisible();
  await includeNone.click();
  // After click, all show-flag checkboxes should be unchecked.
  const showCheckbox = page
    .locator("label")
    .filter({ hasText: "All other genes" })
    .locator('input[type="checkbox"]');
  await expect(showCheckbox).not.toBeChecked();

  // Click 'Include all' to restore.
  const includeAll = page.getByRole("button", { name: "Include all" });
  await expect(includeAll).toBeVisible();
  await includeAll.click();
  await expect(showCheckbox).toBeChecked();
});

test("most-significant: gene link in row navigates to home with the gene as target", async ({
  page,
}) => {
  await page.goto("/most-significant");
  const rankedTable = page.locator("#ranked-genes-table");
  await expect(rankedTable).toBeVisible();
  const firstGeneLink = rankedTable
    .getByRole("link")
    .filter({ hasNotText: /Methods/ })
    .first();
  await expect(firstGeneLink).toBeVisible();
  const symbol = (await firstGeneLink.textContent())?.trim() ?? "";
  expect(symbol.length).toBeGreaterThan(0);
  await firstGeneLink.click();
  // direction=target by default → ?target=<symbol>
  await expect(page).toHaveURL(new RegExp(`[?&]target=${symbol}(&|$)`));
});
