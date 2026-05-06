import { test, expect, type Page } from "@playwright/test";

// Coverage for /all-genes beyond raw pagination: free-text search filters
// the gene list, sort headers swap the row ordering, the page-size dropdown
// changes the visible row count, and clicking a gene row navigates to the
// home page with the right ?target= query.

async function firstSymbolText(page: Page): Promise<string> {
  const link = page.locator('a[href^="/?target="]').first();
  await expect(link).toBeVisible();
  return (await link.locator("div").first().textContent())?.trim() ?? "";
}

test("all-genes: free-text search narrows the result set", async ({ page }) => {
  await page.goto("/all-genes");
  const status = page.getByText(/Showing page \d+ of \d+ · \d+ total genes/);
  await expect(status).toBeVisible();
  const initialText = (await status.textContent()) ?? "";
  const initialTotal = Number(initialText.match(/(\d+)\s+total/)?.[1] ?? "0");
  expect(initialTotal).toBeGreaterThan(0);

  const searchBox = page.getByPlaceholder("Search genes, symbols, or synonyms...");
  await searchBox.fill("BDNF");
  // Debounce is 500ms — wait for the request and the rerender.
  await expect
    .poll(async () => (await status.textContent()) ?? "", { timeout: 5000 })
    .not.toBe(initialText);
  const filteredText = (await status.textContent()) ?? "";
  const filteredTotal = Number(filteredText.match(/(\d+)\s+total/)?.[1] ?? "-1");
  expect(filteredTotal).toBeGreaterThan(0);
  expect(filteredTotal).toBeLessThan(initialTotal);

  // Result rows should include BDNF as one of the human symbols.
  await expect(page.locator('a[href="/?target=BDNF"]').first()).toBeVisible();
});

test("all-genes: search resets to page 1 after paginating", async ({ page }) => {
  await page.goto("/all-genes");
  const status = page.getByText(/Showing page \d+ of \d+/);
  await expect(status).toBeVisible();
  // Advance to page 2.
  const next = page.getByRole("button", { name: "Next" }).first();
  await next.click();
  await expect(status).toContainText(/^Showing page 2 of /);
  // Now type a search; debounced effect resets to page 1.
  const searchBox = page.getByPlaceholder("Search genes, symbols, or synonyms...");
  await searchBox.fill("CHD");
  await expect(status).toContainText(/^Showing page 1 of /, { timeout: 5_000 });
});

test("all-genes: sort by Human symbol toggles the first-row gene", async ({
  page,
}) => {
  await page.goto("/all-genes");
  await expect(page.getByText(/Showing page \d+ of \d+/)).toBeVisible();
  const before = await firstSymbolText(page);

  // The "Human symbol" header is a clickable div with cursor: pointer. Use
  // getByText to find the exact node, then click — Playwright resolves the
  // click to the element with the listener.
  const headerCell = page.getByText("Human symbol", { exact: false }).first();
  await headerCell.click();
  // Sort fires a fetch; wait for the row to actually update.
  await expect
    .poll(() => firstSymbolText(page), {
      timeout: 10_000,
      message: "first row symbol did not change after sorting",
    })
    .not.toBe(before);
});

test("all-genes: page size selector changes the visible row count", async ({
  page,
}) => {
  await page.goto("/all-genes");
  const status = page.getByText(/Showing page \d+ of \d+/);
  await expect(status).toBeVisible();
  // Default is 50; capture row count, then bump to 100 and verify it doubles
  // (modulo the totalPages going down).
  const initialPageCount = await page.locator('a[href^="/?target="]').count();
  expect(initialPageCount).toBeGreaterThan(0);

  const select = page.getByRole("combobox");
  await select.selectOption("100");
  await expect
    .poll(async () => page.locator('a[href^="/?target="]').count(), {
      timeout: 5_000,
    })
    .toBeGreaterThan(initialPageCount);
});

test("all-genes: clicking a row navigates home with the right target", async ({
  page,
}) => {
  await page.goto("/all-genes");
  await expect(page.getByText(/Showing page \d+ of \d+/)).toBeVisible();
  const firstLink = page.locator('a[href^="/?target="]').first();
  const href = await firstLink.getAttribute("href");
  expect(href).toMatch(/^\/\?target=/);
  await firstLink.click();
  await expect(page).toHaveURL(new RegExp(href!.replace(/\?/, "\\?")));
  await expect(page.getByPlaceholder("Target gene")).toBeVisible();
});

test("all-genes: page-number buttons jump to a specific page", async ({
  page,
}) => {
  await page.goto("/all-genes");
  const status = page.getByText(/Showing page \d+ of \d+/);
  await expect(status).toBeVisible();
  // The pager renders page buttons "1", "2", and the last page. "2" is a
  // safe target (always visible when totalPages >= 2).
  const pageTwoBtn = page.getByRole("button", { name: "2", exact: true }).first();
  await expect(pageTwoBtn).toBeVisible();
  await pageTwoBtn.click();
  await expect(status).toContainText(/^Showing page 2 of /);
  await expect(pageTwoBtn).toHaveAttribute("aria-current", "page");
});

test("all-genes: empty search query shows all genes again", async ({ page }) => {
  await page.goto("/all-genes");
  const status = page.getByText(/Showing page \d+ of \d+ · \d+ total genes/);
  await expect(status).toBeVisible();
  const baselineText = (await status.textContent()) ?? "";
  const baselineTotal = Number(baselineText.match(/(\d+)\s+total/)?.[1] ?? "0");

  const searchBox = page.getByPlaceholder("Search genes, symbols, or synonyms...");
  await searchBox.fill("BDNF");
  await expect
    .poll(async () => (await status.textContent()) ?? "", { timeout: 5000 })
    .not.toBe(baselineText);

  await searchBox.fill("");
  await expect
    .poll(async () => {
      const t = (await status.textContent()) ?? "";
      return Number(t.match(/(\d+)\s+total/)?.[1] ?? "0");
    }, { timeout: 5000 })
    .toBe(baselineTotal);
});
