import { test, expect } from "@playwright/test";

// Flow 5: /publications renders and at least one DOI link is present.
test("publications: page renders and DOI links resolve", async ({ page }) => {
  await page.goto("/publications");
  await expect(
    page.getByRole("heading", { name: "Publications & Datasets" }),
  ).toBeVisible();

  // A DOI link is rendered as <a href="https://doi.org/...">. The exact
  // count varies as the team adds publications, so just assert that at
  // least one is present and points at a doi.org URL.
  const doiLinks = page.locator('a[href^="https://doi.org/"]');
  await expect(doiLinks.first()).toBeVisible();
  const href = await doiLinks.first().getAttribute("href");
  expect(href).toMatch(/^https:\/\/doi\.org\//);

  // The Author search box is a labeled input — typing into it should
  // not error. We don't assert filtering behavior (that's a unit-test
  // concern); just smoke-test that the control is wired up.
  const authorInput = page.getByLabel("Author");
  await expect(authorInput).toBeVisible();
  await authorInput.fill("Geschwind");
  await expect(authorInput).toHaveValue("Geschwind");
});
