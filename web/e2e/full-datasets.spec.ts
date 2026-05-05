import { test, expect } from "@playwright/test";

// Flow 7: /full-datasets — the dataset listing page renders, the picker
// loads >0 datasets, and selecting one (via the deterministic ?select=
// URL param) renders that dataset's data table.
//
// Note: ticket #112 says "/all-datasets" but no such page exists — the
// dataset browser lives at /full-datasets. This test covers the
// equivalent flow there.
test("full-datasets: selecting a dataset renders its data table", async ({
  page,
}) => {
  await page.goto("/full-datasets");
  await expect(
    page.getByRole("heading", { name: "Full datasets" }),
  ).toBeVisible();
  // The picker is a search-style input with id=dataset-search.
  const picker = page.getByLabel("Find a dataset");
  await expect(picker).toBeVisible();

  // Pick a dataset deterministically via the listbox: typing a partial
  // name and pressing Enter selects the first match. We use a token
  // that the dev DB consistently has at least one dataset for.
  await picker.click();
  await picker.fill("CRISPR");
  const firstOption = page.getByRole("option").first();
  await expect(firstOption).toBeVisible();
  await firstOption.click();

  // Once a dataset is selected, the URL gains ?select=<slug>, the
  // download buttons appear in the table header, and a DataTable
  // renders below. The "Download TSV" link is a stable landmark.
  await expect(page).toHaveURL(/\/full-datasets\?select=/);
  await expect(
    page.getByRole("link", { name: "Download TSV" }),
  ).toBeVisible();
  // Row-count summary is rendered once data loads. Either pagination
  // or "Showing all N rows" appears.
  await expect(page.getByText(/Showing (rows|all) /)).toBeVisible();
});
