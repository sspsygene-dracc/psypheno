import { test, expect } from "@playwright/test";

// The author line on /publications: collapsed to first-3 … last by default,
// auto-expanded with the matched author highlighted when the Author facet is
// used. A middle author is the case that motivated this — searching for one
// used to filter the list down to papers whose author line never showed the
// name that caused the match.

test("publications: author line collapses to first three and the last author", async ({
  page,
}) => {
  await page.goto("/publications");
  // Find a paper long enough to be collapsed — the "(N more)" control only
  // renders when authors are actually hidden.
  const moreButton = page.getByRole("button", { name: /^\(\d+ more\)$/ }).first();
  await expect(moreButton).toBeVisible();

  const line = moreButton.locator("xpath=..");
  const text = (await line.textContent()) ?? "";
  // first, second, third, …, last (N more)
  expect(text).toMatch(/…,/);
  const namesBeforeEllipsis = text.split("…")[0].split(",").filter((s) => s.trim());
  expect(namesBeforeEllipsis).toHaveLength(3);

  // Expanding drops the ellipsis and offers the inverse control.
  await moreButton.click();
  await expect(page.getByRole("button", { name: "show fewer" }).first()).toBeVisible();
});

test("publications: searching an author highlights the match and expands the list", async ({
  page,
}) => {
  await page.goto("/publications");
  await page.getByLabel("Author").fill("Geschwind");

  // Every visible card must show the matched author, highlighted — including
  // when they sit in the hidden middle of the list.
  const marks = page.locator("mark");
  await expect(marks.first()).toBeVisible();
  const count = await marks.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    await expect(marks.nth(i)).toContainText(/Geschwind/i);
  }
});

test("publications: clearing the author search re-collapses the author lists", async ({
  page,
}) => {
  await page.goto("/publications");
  const authorInput = page.getByLabel("Author");
  await authorInput.fill("Geschwind");
  await expect(page.locator("mark").first()).toBeVisible();

  await authorInput.fill("");
  await expect(page.locator("mark")).toHaveCount(0);
  // Long author lists are collapsed again after the query goes away.
  await expect(
    page.getByRole("button", { name: /^\(\d+ more\)$/ }).first(),
  ).toBeVisible();
});

test("publications: card headline is the paper title, not the author citation", async ({
  page,
}) => {
  await page.goto("/publications");
  // Titles come from each dataset config's `publication.title`. Pick a paper
  // that is stable in the corpus.
  await page.getByLabel("Author").fill("Velmeshev");
  await expect(
    page.getByText(
      "Single-cell genomics identifies cell type-specific molecular changes in autism",
    ),
  ).toBeVisible();
});
