import { test, expect } from "@playwright/test";
import { selectGeneInBox, waitForResults } from "./helpers";

// Flow 2: Home → pair-mode search → perturbed/target results render.
test("home: perturbed + target pair narrows the result set", async ({ page }) => {
  await page.goto("/");
  await selectGeneInBox(page, "Perturbed gene", "FOXG1");
  await selectGeneInBox(page, "Target gene", "BDNF");
  const heading = await waitForResults(page);
  // Heading should reflect both selections.
  await expect(heading).toContainText("FOXG1");
  await expect(heading).toContainText("BDNF");
  // The two side panels label the perturbed and target genes
  // respectively. Their text is uppercased via CSS, so match
  // case-insensitively.
  await expect(
    page.getByText(/Perturbed gene:\s*FOXG1/i).first(),
  ).toBeVisible();
  await expect(
    page.getByText(/Target gene:\s*BDNF/i).first(),
  ).toBeVisible();
});
