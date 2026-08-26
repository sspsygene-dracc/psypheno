import { describe, expect, it } from "vitest";

import { isRestricted, restrictionLabel } from "@/lib/destination-labels";

/**
 * The "not on production" badge is a safety signal for wranglers (#225): it
 * appears only to warn that a dataset is NOT cleared for prod. The asymmetry
 * matters — a missing badge must never be read as "confirmed public", because
 * a DB built before #225 carries no destinations at all.
 */
describe("isRestricted", () => {
  it("flags an internal-only dataset", () => {
    expect(isRestricted(["dev", "int"])).toBe(true);
    expect(restrictionLabel(["dev", "int"])).toBe("Internal only");
  });

  it("flags a dev-only dataset", () => {
    expect(isRestricted(["dev"])).toBe(true);
    expect(restrictionLabel(["dev"])).toBe("Dev only");
  });

  it("stays silent once the dataset is cleared for prod", () => {
    for (const d of [["dev", "int", "prod"], ["dev", "prod"], ["prod"]]) {
      expect(isRestricted(d)).toBe(false);
      expect(restrictionLabel(d)).toBeNull();
    }
  });

  it("stays silent when destinations are unknown", () => {
    // A DB built before #225. Badging every dataset here would be misleading.
    expect(isRestricted(null)).toBe(false);
    expect(isRestricted(undefined)).toBe(false);
    expect(isRestricted([])).toBe(false);
    expect(restrictionLabel(null)).toBeNull();
  });

  it("keys off prod membership, not list length", () => {
    expect(isRestricted(["int"])).toBe(true);
    expect(isRestricted(["int", "prod"])).toBe(false);
  });
});
