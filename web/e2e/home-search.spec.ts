import { test, expect } from "@playwright/test";
import { selectGeneInBox, waitForResults } from "./helpers";

// Flow 1: Home → general gene search (target only) → results page renders.
test("home: general gene search renders results section", async ({ page }) => {
  await page.goto("/");
  // The two search inputs are the page's stable landmark — wait for
  // both to mount before interacting.
  await expect(page.getByPlaceholder("Perturbed gene")).toBeVisible();
  await expect(page.getByPlaceholder("Target gene")).toBeVisible();
  // Enter a well-known gene as the target. FOXG1 is present across
  // many SSPsyGene datasets, so we expect at least one results table.
  await selectGeneInBox(page, "Target gene", "FOXG1");
  const heading = await waitForResults(page);
  await expect(heading).toContainText("FOXG1");
  // At least one dataset section should render with its "View full
  // data table" link, or the explicit "no results" notice.
  const datasetLinks = page.getByRole("link", {
    name: /View full data table/,
  });
  const noResults = page.getByText(/No results found in any dataset/);
  await expect(datasetLinks.first().or(noResults)).toBeVisible();
});
