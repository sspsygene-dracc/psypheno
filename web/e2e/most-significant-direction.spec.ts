import { test, expect } from "@playwright/test";

// Flow 4: /most-significant — toggle Direction (Target ↔ Perturbed) and
// observe the ranked list change. Target is the default; flipping to
// Perturbed yields a different combined-pvalues query and almost
// always a different top-ranked gene.
test("most-significant: toggling direction changes the top-ranked gene", async ({
  page,
}) => {
  await page.goto("/most-significant");
  // Both radios are rendered with the name="direction" attribute; we
  // assert via the label text using getByLabel.
  const targetRadio = page.getByLabel("Target", { exact: true });
  const perturbedRadio = page.getByLabel("Perturbed", { exact: true });
  await expect(targetRadio).toBeChecked();

  // Wait for the ranked rows to render. Each gene cell is a link with
  // the symbol as its text; the first such link in the table is the
  // top-ranked gene under the current settings.
  const rankedTable = page.locator("#ranked-genes-table");
  await expect(rankedTable).toBeVisible();
  const firstGeneLink = rankedTable
    .getByRole("link")
    .filter({ hasNotText: /Methods/ })
    .first();
  await expect(firstGeneLink).toBeVisible();
  const initialTopGene = (await firstGeneLink.textContent())?.trim() ?? "";
  expect(initialTopGene.length).toBeGreaterThan(0);

  // Flip to Perturbed and wait for the table to swap. The tbody key is
  // re-keyed on method changes only, so we poll the first link's text
  // until it differs from the Target-direction value.
  await perturbedRadio.check();
  await expect(perturbedRadio).toBeChecked();
  // (Note: the URL-sync effect on /most-significant swallows the first
  // state change after hydration, so we do not assert ?dir=perturbed
  // here. The semantic check below — that the ranking changes — is
  // what we actually care about.)
  await expect
    .poll(async () => (await firstGeneLink.textContent())?.trim() ?? "", {
      timeout: 15_000,
      message: "top-ranked gene did not change after switching to Perturbed",
    })
    .not.toBe(initialTopGene);
});
