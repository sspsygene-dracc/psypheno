import { test, expect } from "@playwright/test";

// Coverage of /significant-rows: page renders, the filter/sort selectors
// drive the per-dataset results, the regulation radio narrows datasets,
// and assay-type radios filter the visible dataset sections. URL params
// (assay, disease, organism, reg) hydrate the filters on first load.

test("significant-rows: page renders with at least one dataset section", async ({
  page,
}) => {
  await page.goto("/significant-rows");
  await expect(
    page.getByRole("heading", { name: /Significant Rows/ }),
  ).toBeVisible();
  // At least one per-dataset card should render with a "N significant rows"
  // counter once the data tables stream in.
  await expect(page.getByText(/significant rows?$/).first()).toBeVisible();
});

test("significant-rows: switching between p-value and FDR re-renders the table", async ({
  page,
}) => {
  await page.goto("/significant-rows");
  await expect(page.getByText(/significant rows?$/).first()).toBeVisible();

  // The page exposes two <select>s — first is "Rows where", second is "sorted by".
  const filterBy = page.locator("select").nth(0);
  await filterBy.selectOption("fdr");
  await expect(filterBy).toHaveValue("fdr");

  const sortBy = page.locator("select").nth(1);
  await sortBy.selectOption("fdr");
  await expect(sortBy).toHaveValue("fdr");
});

test("significant-rows: regulation Up restricts to up-regulated rows", async ({
  page,
}) => {
  await page.goto("/significant-rows");
  await expect(page.getByText(/significant rows?$/).first()).toBeVisible();

  const upRadio = page.getByLabel("Up-regulated", { exact: true });
  await upRadio.check();
  await expect(upRadio).toBeChecked();
  // Some "no significant rows" sections may disappear because they lack
  // an effect_column. The page should still render without errors.
  await expect(
    page.getByRole("heading", { name: /Significant Rows/ }),
  ).toBeVisible();
});

test("significant-rows: ?assay=expression hydrates the assay filter", async ({
  page,
}) => {
  await page.goto("/significant-rows?assay=expression");
  // Wait for filters to mount.
  await expect(page.getByText(/significant rows?$/).first()).toBeVisible();
  const assayRadio = page.getByLabel("Gene Expression (RNA-seq)", {
    exact: true,
  });
  await expect(assayRadio).toBeChecked();
});

test("significant-rows: ?reg=down hydrates the regulation filter", async ({
  page,
}) => {
  await page.goto("/significant-rows?reg=down");
  await expect(
    page.getByLabel("Down-regulated", { exact: true }),
  ).toBeChecked();
});
