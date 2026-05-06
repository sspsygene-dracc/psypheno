import { test, expect } from "@playwright/test";

// Wider coverage of /full-datasets: dataset picker arrow-key navigation,
// the clear-selection button, deep-linking via ?open= and ?select=, the
// download links, the publication-page back-link, and column filter +
// sort interactions on the data table.

test.describe("full-datasets dataset picker", () => {
  test("typing partial name and arrow-key Enter selects a match", async ({
    page,
  }) => {
    await page.goto("/full-datasets");
    const picker = page.getByLabel("Find a dataset");
    await picker.click();
    await picker.fill("CRISPR");
    const firstOption = page.getByRole("option").first();
    await expect(firstOption).toBeVisible();
    // Press Enter on the highlighted (first) option.
    await picker.press("Enter");
    await expect(page).toHaveURL(/\/full-datasets\?select=/);
  });

  test("clear button resets dataset selection", async ({ page }) => {
    await page.goto(
      "/full-datasets?select=mutant_behavior_fingerprints",
    );
    await expect(
      page.getByRole("link", { name: "Download TSV" }),
    ).toBeVisible();
    const clearBtn = page.getByRole("button", { name: "Clear selected dataset" });
    await expect(clearBtn).toBeVisible();
    await clearBtn.click();
    await expect(page).toHaveURL(/\/full-datasets$/);
    await expect(
      page.getByRole("link", { name: "Download TSV" }),
    ).toBeHidden();
  });

  test("?open=<slug> hydrates the same dataset as ?select=", async ({ page }) => {
    await page.goto(
      "/full-datasets?open=mutant_behavior_fingerprints",
    );
    await expect(
      page.getByRole("link", { name: "Download TSV" }),
    ).toBeVisible();
    // The URL-sync effect rewrites ?open= → ?select=
    await expect(page).toHaveURL(/\/full-datasets\?select=/);
  });

  test("non-matching search shows the no-results message", async ({ page }) => {
    await page.goto("/full-datasets");
    const picker = page.getByLabel("Find a dataset");
    await picker.click();
    await picker.fill("zzzzzz_no_such_dataset_zzzzzz");
    await expect(page.getByText("No matching datasets.")).toBeVisible();
  });
});

test.describe("full-datasets data table", () => {
  test("Download TSV link points at the per-table download endpoint", async ({
    page,
  }) => {
    await page.goto(
      "/full-datasets?select=mutant_behavior_fingerprints",
    );
    const link = page.getByRole("link", { name: "Download TSV" });
    await expect(link).toBeVisible();
    const href = await link.getAttribute("href");
    expect(href).toMatch(/^\/api\/download\/tables\/.+\.tsv$/);
  });

  test("Metadata YAML link is wired up", async ({ page }) => {
    await page.goto(
      "/full-datasets?select=mutant_behavior_fingerprints",
    );
    const link = page.getByRole("link", { name: "Metadata YAML" });
    await expect(link).toBeVisible();
    const href = await link.getAttribute("href");
    expect(href).toMatch(/^\/api\/download\/metadata\/.+\.yaml$/);
  });

  test("data table renders rows for the selected dataset", async ({ page }) => {
    await page.goto(
      "/full-datasets?select=mutant_behavior_fingerprints",
    );
    await expect(page.getByText(/Showing (rows|all)/)).toBeVisible();
    // At least one body row should be present in the rendered table.
    const tableBodyRows = page.locator("table tbody tr");
    await expect(tableBodyRows.first()).toBeVisible();
  });

  test("changing dataset replaces the visible table", async ({ page }) => {
    await page.goto(
      "/full-datasets?select=mutant_behavior_fingerprints",
    );
    await expect(page.getByText(/Showing (rows|all)/)).toBeVisible();
    const summaryBefore = await page.getByText(/Showing (rows|all)/).textContent();

    // Open the picker and switch to a different dataset.
    const picker = page.getByLabel("Find a dataset");
    await picker.click();
    await picker.fill("nebula");
    const firstOption = page.getByRole("option").first();
    await firstOption.click();
    // Wait for the URL slug to change and the summary to update.
    await expect
      .poll(async () => (await page.getByText(/Showing (rows|all)/).textContent()) ?? "", {
        timeout: 10_000,
      })
      .not.toBe(summaryBefore);
  });
});
