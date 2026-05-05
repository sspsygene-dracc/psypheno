import { test, expect } from "@playwright/test";

// Flow 6: /all-genes pagination — Next moves to page 2 and the visible
// row set changes.
test("all-genes: Next button advances pagination", async ({ page }) => {
  await page.goto("/all-genes");
  await expect(
    page.getByRole("heading", { name: "All Genes" }),
  ).toBeVisible();

  // The footer carries "Showing page X of Y · N total genes" once the
  // first fetch resolves. Wait for it before asserting button state.
  const pageStatus = page.getByText(/Showing page \d+ of \d+/);
  await expect(pageStatus).toBeVisible();
  await expect(pageStatus).toContainText(/^Showing page 1 of /);

  // Capture a row-identifying snapshot (first gene symbol cell text)
  // so we can verify the contents change after pagination.
  const firstSymbolBefore = await firstSymbolCellText(page);

  // Multiple "Next" buttons exist (top + bottom of pager region in
  // some renders). Use the active one near the page-status footer.
  const nextBtn = page.getByRole("button", { name: "Next" }).first();
  await expect(nextBtn).toBeEnabled();
  await nextBtn.click();
  await expect(pageStatus).toContainText(/^Showing page 2 of /);

  const firstSymbolAfter = await firstSymbolCellText(page);
  expect(firstSymbolAfter).not.toEqual(firstSymbolBefore);
});

async function firstSymbolCellText(page: import("@playwright/test").Page) {
  // The gene rows are <Link>s wrapping a 5-column grid. We can't rely
  // on a per-row test id, so grab the first cell of the first row by
  // walking the gene list section. The header row is also a div with
  // the column titles — skip it by anchoring on a Link parent.
  const link = page.locator('a[href^="/?target="]').first();
  await expect(link).toBeVisible();
  return (await link.locator("div").first().textContent())?.trim() ?? "";
}
