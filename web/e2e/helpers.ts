import { expect, type Page, type Locator } from "@playwright/test";

/**
 * Type a gene symbol into one of the home-page search boxes (perturbed
 * or target) and pick the matching autocomplete suggestion. Resolves
 * once the URL reflects the selection so callers can chain assertions.
 */
export async function selectGeneInBox(
  page: Page,
  boxLabel: "Perturbed gene" | "Target gene",
  symbol: string,
) {
  const input = page.getByPlaceholder(boxLabel);
  await input.click();
  await input.fill(symbol);
  // Suggestion dropdown shows "<SYMBOL> (human)" — pick the row that
  // contains the symbol followed by "(human)" to avoid synonym matches.
  const suggestion = page
    .locator('div[role="listbox"], div')
    .filter({ hasText: new RegExp(`^${symbol}\\s*\\(human\\)`) })
    .first();
  // The dropdown is a plain div, so fall back to any visible item that
  // starts with the symbol if the role-scoped match doesn't apply.
  const fallback = page.getByText(`${symbol} (human)`, { exact: false }).first();
  await Promise.race([
    suggestion.waitFor({ state: "visible", timeout: 5000 }).catch(() => {}),
    fallback.waitFor({ state: "visible", timeout: 5000 }).catch(() => {}),
  ]);
  // Prefer keyboard-Enter selection — the dropdown highlights the first
  // result and Enter commits it. This sidesteps the dropdown being
  // multiple overlapping divs.
  await input.press("Enter");
  const queryParam = boxLabel === "Perturbed gene" ? "perturbed" : "target";
  await expect(page).toHaveURL(new RegExp(`[?&]${queryParam}=${symbol}`));
}

/**
 * Wait for the home-page results region to render — the
 * "Results for ..." heading is rendered once data has loaded for the
 * selected gene(s).
 */
export async function waitForResults(page: Page): Promise<Locator> {
  const heading = page.getByRole("heading", { name: /^Results for/ });
  await expect(heading).toBeVisible();
  return heading;
}
