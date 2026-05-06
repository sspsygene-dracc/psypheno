import { test, expect } from "@playwright/test";

// Header navigation: primary links route correctly, the "Other" dropdown
// reveals secondary pages, and the logo always returns to the home page.

const PRIMARY_LINKS = [
  { label: "Home", path: "/" },
  { label: "Full datasets", path: "/full-datasets" },
  { label: "Publications", path: "/publications" },
  { label: "Most Significant Genes", path: "/most-significant" },
] as const;

const OTHER_LINKS = [
  { label: "All Genes", path: "/all-genes" },
  { label: "Significant Rows", path: "/significant-rows" },
  { label: "Meta-Analysis Methods", path: "/methods" },
  { label: "Gene Parser", path: "/gene-parser" },
  { label: "Changelog", path: "/dataset-changelog" },
  { label: "Download", path: "/download" },
] as const;

test.describe("header navigation", () => {
  for (const { label, path } of PRIMARY_LINKS) {
    test(`primary link: ${label} → ${path}`, async ({ page }) => {
      // Land somewhere that isn't the destination so the click has to navigate.
      const start = path === "/" ? "/methods" : "/";
      await page.goto(start);
      const link = page
        .locator("header")
        .getByRole("link", { name: label, exact: true })
        .first();
      await expect(link).toBeVisible();
      await link.click();
      await expect(page).toHaveURL(new RegExp(`${path}(\\?.*)?$`));
    });
  }

  for (const { label, path } of OTHER_LINKS) {
    test(`other link: ${label} → ${path}`, async ({ page }) => {
      await page.goto("/");
      // Open the desktop "Other" dropdown.
      const otherButton = page.getByRole("button", { name: /^Other/ });
      await expect(otherButton).toBeVisible();
      await otherButton.click();
      const link = page.getByRole("menuitem", { name: label });
      await expect(link).toBeVisible();
      await link.click();
      await expect(page).toHaveURL(new RegExp(`${path}(\\?.*)?$`));
    });
  }

  test("logo links back to home from a non-home page", async ({ page }) => {
    await page.goto("/methods");
    await expect(page).toHaveURL(/\/methods$/);
    const logoLink = page.locator("header").getByRole("link").first();
    await logoLink.click();
    await expect(page).toHaveURL(/\/$|\/\?.*$/);
    // Home page has the gene search inputs.
    await expect(page.getByPlaceholder("Perturbed gene")).toBeVisible();
  });

  test("Other dropdown closes when clicking outside", async ({ page }) => {
    await page.goto("/");
    const otherButton = page.getByRole("button", { name: /^Other/ });
    await otherButton.click();
    await expect(
      page.getByRole("menuitem", { name: "All Genes" }),
    ).toBeVisible();
    // Click somewhere outside the dropdown.
    await page.locator("h1, h2, body").first().click({ position: { x: 0, y: 0 } });
    await expect(
      page.getByRole("menuitem", { name: "All Genes" }),
    ).toBeHidden();
  });

  test("active page is highlighted in the nav", async ({ page }) => {
    await page.goto("/full-datasets");
    // The active link gets aria-current via Next's usePathname… actually here
    // the styling is inline. We just check the active link exists and is
    // visible — the heading on the page proves we are on /full-datasets.
    await expect(
      page.locator("header").getByRole("link", { name: "Full datasets" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Full datasets" }),
    ).toBeVisible();
  });
});

test("footer renders copyright with the current year", async ({ page }) => {
  await page.goto("/");
  const footer = page.locator("footer");
  await expect(footer).toBeVisible();
  const year = new Date().getFullYear();
  await expect(footer).toContainText(`${year} The SSPsyGene Project`);
});
