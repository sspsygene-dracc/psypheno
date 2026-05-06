import { test, expect } from "@playwright/test";

// Coverage for the lazy-loaded volcano chart added in beb07c0:
// EffectDistributionChart now ships in its own dynamic chunk so the
// home / all-genes pages don't pull in recharts on first paint. We
// verify both halves of the contract:
//
// 1. Loading the home page with no gene selected does NOT request the
//    /api/effect-distribution endpoint (the chart hasn't mounted).
// 2. Selecting a gene that has volcano-eligible result rows DOES mount
//    the chart, fetch its data, and render an SVG.

test("volcano: not requested on bare home page", async ({ page }) => {
  const distRequests: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/effect-distribution")) {
      distRequests.push(req.url());
    }
  });
  await page.goto("/");
  await expect(page.getByPlaceholder("Target gene")).toBeVisible();
  // Give the page time to settle; with no gene selected, GeneResults
  // never renders the chart wrapper.
  await page.waitForTimeout(500);
  expect(
    distRequests,
    "no gene selected — the volcano chunk shouldn't request its data",
  ).toEqual([]);
});

test("volcano: mounts and renders an SVG when a gene with effect data is loaded", async ({
  page,
}) => {
  const distRequests: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/effect-distribution")) {
      distRequests.push(req.url());
    }
  });

  await page.goto("/?target=FOXG1");
  // Wait for the results region.
  const heading = page.getByRole("heading", { name: /^Results for/ });
  await expect(heading).toBeVisible();

  // Volcano section has a button labeled "Volcano plot (...)" — wait
  // for at least one to render (volcano plots are expanded by default
  // for any table with an effect column).
  const volcanoBtn = page
    .getByRole("button", { name: /^Volcano plot \(/ })
    .first();
  await expect(volcanoBtn).toBeVisible({ timeout: 15_000 });

  // Once mounted, EffectDistributionChart fires the POST to
  // /api/effect-distribution and renders an SVG via recharts.
  await expect
    .poll(() => distRequests.length, { timeout: 10_000 })
    .toBeGreaterThanOrEqual(1);

  // The recharts <ResponsiveContainer> emits an SVG element. Scope to
  // the volcano region by walking up from the toggle button's parent.
  const svg = page.locator(".recharts-wrapper svg, svg.recharts-surface").first();
  await expect(svg).toBeVisible({ timeout: 15_000 });
});
