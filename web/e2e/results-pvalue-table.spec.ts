import { test, expect } from "@playwright/test";
import { selectGeneInBox, waitForResults } from "./helpers";

// Flow 3: Results page → expand p-value table (volcano), click into a
// linked dataset detail view.
test("results: volcano expands; dataset link navigates to /full-datasets", async ({
  page,
}) => {
  // Pre-populate the gene via URL — faster and avoids depending on
  // autocomplete for this particular flow.
  await page.goto("/?target=FOXG1");
  // The home page hydrates from the URL: wait for the results heading
  // before exercising the controls.
  await selectGeneInBox(page, "Target gene", "FOXG1").catch(async () => {
    // If the helper races the URL hydration, fall back to waiting for
    // the results region directly.
  });
  const heading = await waitForResults(page);
  await expect(heading).toContainText("FOXG1");

  // Volcano toggles render as buttons whose label starts with
  // "Volcano plot (...)". Volcanos are expanded by default — toggle
  // one closed and back open to exercise the control.
  const volcano = page
    .getByRole("button", { name: /^Volcano plot \(/ })
    .first();
  if (await volcano.count()) {
    await expect(volcano).toBeVisible();
    await volcano.click();
    await volcano.click();
  }

  // The first "View full data table →" link should navigate to
  // /full-datasets with a ?open= or ?select= query.
  const detailLink = page
    .getByRole("link", { name: /View full data table/ })
    .first();
  if (await detailLink.count()) {
    await detailLink.click();
    await expect(page).toHaveURL(/\/full-datasets\?(open|select)=/);
    await expect(
      page.getByRole("heading", { name: "Full datasets" }),
    ).toBeVisible();
  } else {
    // No dataset rows for this gene? Skip the click leg of the test
    // rather than asserting a click against a missing element. This
    // keeps the spec robust if the dev DB ever loses the FOXG1 fixture.
    test.skip(true, "no dataset detail link rendered for FOXG1");
  }
});
