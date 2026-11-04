import { test, expect, type Page, type Locator } from "@playwright/test";

// /matrix keeps one grid mounted across view changes. A horizontal offset that
// was valid for a wide column set (e.g. "By study", 25 per dataset) must not
// leave a narrower one (Summary, a different per-dataset count, "By readout")
// scrolled past its last column — that rendered a blank grid with only the
// row stripes showing.

const canvasSel = 'canvas[aria-label^="Cross-modality heatmap"]';

function nColsFromLabel(label: string | null): number {
  const m = label?.match(/by (\d+) measurement columns/);
  return m ? Number(m[1]) : -1;
}

async function currentCols(page: Page): Promise<number> {
  return nColsFromLabel(await page.locator(canvasSel).getAttribute("aria-label"));
}

/** Click a view control and wait until the grid shows a different column count. */
async function switchTo(page: Page, button: Locator) {
  const before = await currentCols(page);
  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => currentCols(page), { timeout: 20_000 }).not.toBe(before);
}

async function scrollState(page: Page) {
  return page.locator(canvasSel).evaluate((canvas) => {
    const body = canvas.parentElement as HTMLElement;
    const bodyRect = body.getBoundingClientRect();
    // The rendered column labels, and how many of them sit inside the visible
    // header (i.e. over the visible part of the body).
    const header = document.querySelector(".matrix-label-strip") as HTMLElement;
    const labels = Array.from(header.firstElementChild?.children ?? []);
    const visibleLabels = labels.filter((l) => {
      const r = l.getBoundingClientRect();
      return r.right > bodyRect.left && r.left < bodyRect.right;
    }).length;
    return {
      scrollLeft: body.scrollLeft,
      maxLeft: Math.max(0, body.scrollWidth - body.clientWidth),
      scrollTop: body.scrollTop,
      // The sizer's width is the real content width (nCols × column pitch).
      contentW: (body.firstElementChild as HTMLElement).offsetWidth,
      clientW: body.clientWidth,
      visibleLabels,
    };
  });
}

async function scrollBody(page: Page, left: number, top: number) {
  await page.locator(canvasSel).evaluate(
    (canvas, [l, t]) => {
      const body = canvas.parentElement as HTMLElement;
      body.scrollLeft = l;
      body.scrollTop = t;
    },
    [left, top]
  );
  // Let the scroll handler sync the header (it runs on the next frame).
  await expect.poll(async () => (await scrollState(page)).scrollLeft).toBeGreaterThan(0);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(null))));
}

function expectInView(s: Awaited<ReturnType<typeof scrollState>>) {
  // The offset lies inside the content (no stale scroll overflow) …
  expect(s.scrollLeft).toBeLessThanOrEqual(Math.max(0, s.contentW - s.clientW));
  expect(s.maxLeft).toBeLessThanOrEqual(Math.max(0, s.contentW - s.clientW) + 1);
  // … and the header actually renders labels over the visible cells.
  expect(s.visibleLabels).toBeGreaterThan(0);
}

test.beforeEach(async ({ page }) => {
  await page.goto("/matrix");
  await expect(page.locator(canvasSel)).toBeVisible({ timeout: 30_000 });
  await expect.poll(() => currentCols(page), { timeout: 30_000 }).toBeGreaterThan(0);
});

test("matrix: Summary after scrolling far right shows its columns from the left", async ({
  page,
}) => {
  await scrollBody(page, 2400, 200);
  const before = await scrollState(page);

  await switchTo(page, page.getByRole("button", { name: "Summary", exact: true }));
  await expect.poll(async () => (await scrollState(page)).visibleLabels).toBeGreaterThan(0);
  const s = await scrollState(page);
  expect(s.scrollLeft).toBe(0);
  expectInView(s);
  // Rows are unchanged by a column switch, so the vertical offset is kept.
  expect(s.scrollTop).toBe(before.scrollTop);

  // Reverse direction: back to the expanded view starts at the left edge too.
  await switchTo(page, page.getByRole("button", { name: "25", exact: true }));
  const back = await scrollState(page);
  expect(back.scrollLeft).toBe(0);
  expectInView(back);
});

test("matrix: changing columns per dataset while scrolled right stays in view", async ({
  page,
}) => {
  await switchTo(page, page.getByRole("button", { name: "200", exact: true }));
  // Scroll to the far right edge of the wide view.
  await scrollBody(page, 1e7, 0);
  await switchTo(page, page.getByRole("button", { name: "5", exact: true }));
  await expect.poll(async () => (await scrollState(page)).visibleLabels).toBeGreaterThan(0);
  expectInView(await scrollState(page));
});

test("matrix: switching to By readout while scrolled right stays in view", async ({
  page,
}) => {
  const readout = page.getByRole("button", { name: "By readout, across studies" });
  test.skip(await readout.isDisabled(), "overview DB has no collated tables");
  await scrollBody(page, 1e7, 0);
  await switchTo(page, readout);
  await expect.poll(async () => (await scrollState(page)).visibleLabels).toBeGreaterThan(0);
  expectInView(await scrollState(page));
});
