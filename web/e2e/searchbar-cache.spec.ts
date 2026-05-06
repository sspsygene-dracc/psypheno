import { test, expect } from "@playwright/test";

// Regression for the SearchBar module-level LRU added in beb07c0:
// typing "BRCA" → backspace to "BRC" → re-add "A" must hit the network
// only TWICE (once per unique prefix). The third "BRCA" lookup must be
// served from the in-memory cache without a fetch.
//
// Counts requests to /api/search-text via page.on('request'). The
// SearchBar debounces at 200 ms; we explicitly wait for each fetch's
// RESPONSE before the next keystroke, so the cleanup AbortController
// doesn't cancel an in-flight fetch and skip the cacheSet call.

test("SearchBar LRU: re-typing a previously-seen prefix doesn't re-fetch", async ({
  page,
}) => {
  await page.goto("/");
  const input = page.getByPlaceholder("Target gene");
  await expect(input).toBeVisible();

  const hits: string[] = [];
  page.on("request", (req) => {
    const url = req.url();
    if (url.includes("/api/search-text")) hits.push(url);
  });

  // Type BRCA — fires one request after the 200 ms debounce. Wait for
  // the response so the LRU is populated before the next keystroke.
  await input.click();
  await input.fill("BRCA");
  await page.waitForResponse(
    (resp) =>
      resp.url().includes("/api/search-text") &&
      resp.url().includes("text=BRCA") &&
      resp.status() === 200,
    { timeout: 5_000 },
  );

  // Backspace → "BRC" → fires a second request. Same wait-for-response.
  await input.press("Backspace");
  await page.waitForResponse(
    (resp) => {
      const u = resp.url();
      return (
        u.includes("/api/search-text") &&
        /text=BRC(?!A)/.test(u) &&
        resp.status() === 200
      );
    },
    { timeout: 5_000 },
  );

  const beforeReadd = hits.length;

  // Re-add "A" → "BRCA" → must NOT fetch (cache hit).
  await input.press("End");
  await input.press("A");
  // Wait past the 200 ms debounce + slack. If the SearchBar were going
  // to fetch, it'd fire by now.
  await page.waitForTimeout(500);

  const afterReadd = hits.length;
  expect(
    afterReadd,
    `expected the BRCA cache hit to short-circuit the network — saw ${afterReadd - beforeReadd} new request(s) after re-typing. All hits: ${JSON.stringify(hits)}`,
  ).toBe(beforeReadd);

  // And the dropdown still shows BRCA suggestions, served from cache.
  await expect(
    page.getByText(/BRCA\d?\s*\(human\)/i).first(),
  ).toBeVisible();
});
