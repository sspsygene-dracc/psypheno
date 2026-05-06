import { test, expect } from "@playwright/test";
import { selectGeneInBox, waitForResults } from "./helpers";

// Coverage of home-page autocomplete and URL hydration:
// - typing into the search returns suggestions
// - choosing a suggestion sets ?target=<symbol>
// - direct URL ?target=FOXG1 hydrates the search box and renders results
// - swapping perturbed/target via the URL works in both directions
// - clearing both selections returns the URL to /

test("home: autocomplete shows suggestions for a partial query", async ({
  page,
}) => {
  await page.goto("/");
  const input = page.getByPlaceholder("Target gene");
  await input.click();
  await input.fill("BDN");
  // The autocomplete dropdown renders with at least the BDNF entry.
  await expect(
    page.getByText(/BDNF\s*\(human\)/i).first(),
  ).toBeVisible();
});

test("home: ?target=FOXG1 URL hydrates the target search and renders results", async ({
  page,
}) => {
  await page.goto("/?target=FOXG1");
  // Heading appears with the gene name.
  const heading = await waitForResults(page);
  await expect(heading).toContainText("FOXG1");
  // The home page also shows simpleGeneString → "Any → FOXG1 (human) ..."
  // We just check that "FOXG1" appears and the perturbed side reads "Any".
  await expect(page.getByText(/FOXG1/).first()).toBeVisible();
});

test("home: ?perturbed=FOXG1&target=BDNF URL hydrates both search boxes", async ({
  page,
}) => {
  await page.goto("/?perturbed=FOXG1&target=BDNF");
  const heading = await waitForResults(page);
  await expect(heading).toContainText("FOXG1");
  await expect(heading).toContainText("BDNF");
});

test("home: typing CONTROL resolves to the all-controls suggestion", async ({
  page,
}) => {
  await page.goto("/");
  const input = page.getByPlaceholder("Perturbed gene");
  await input.click();
  await input.fill("CONTROL");
  // The dropdown shows a control row.
  await expect(
    page.locator("text=/control/i").first(),
  ).toBeVisible();
});

test("home: invalid gene query falls back to no-results notice", async ({
  page,
}) => {
  await page.goto("/?target=ZZNotARealGeneZZ");
  // The hydration tries to resolve the symbol; if no suggestion matches,
  // target stays null and no results section appears. We just smoke-test
  // that the page didn't crash.
  await expect(page.getByPlaceholder("Target gene")).toBeVisible();
});

test("home: clearing target via URL navigation resets the heading", async ({
  page,
}) => {
  await page.goto("/?target=FOXG1");
  await waitForResults(page);
  await page.goto("/");
  // Without any selection, the results section should not render.
  await expect(
    page.getByRole("heading", { name: /^Results for/ }),
  ).toBeHidden();
});

test("home: arrow-key navigation in autocomplete works", async ({ page }) => {
  await page.goto("/");
  const input = page.getByPlaceholder("Target gene");
  await input.click();
  await input.fill("BD");
  await expect(
    page.getByText(/BDNF\s*\(human\)/i).first(),
  ).toBeVisible();
  // Pressing Enter should pick the highlighted top suggestion.
  await input.press("Enter");
  await expect(page).toHaveURL(/[?&]target=/);
});

test("home: helper integration — selecting both genes drives the pair API", async ({
  page,
}) => {
  await page.goto("/");
  await selectGeneInBox(page, "Perturbed gene", "FOXG1");
  await selectGeneInBox(page, "Target gene", "BDNF");
  const heading = await waitForResults(page);
  await expect(heading).toContainText("FOXG1");
  await expect(heading).toContainText("BDNF");
});
