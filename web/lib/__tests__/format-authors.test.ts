import { describe, it, expect } from "vitest";
import { formatAuthors } from "@/lib/format-authors";

describe("formatAuthors", () => {
  it("returns empty string when both first and last are missing", () => {
    expect(formatAuthors(null, null, null)).toBe("");
    expect(formatAuthors(undefined, undefined, undefined)).toBe("");
    expect(formatAuthors("", "", 0)).toBe("");
  });

  it("returns the single name when first and last are equal", () => {
    expect(formatAuthors("Smith", "Smith", 1)).toBe("Smith");
  });

  it("uses ellipsis form when count > 2", () => {
    expect(formatAuthors("Smith", "Jones", 5)).toBe("Smith, ..., Jones");
  });

  it("uses ampersand form when count <= 2", () => {
    expect(formatAuthors("Smith", "Jones", 2)).toBe("Smith & Jones");
  });

  it("uses ampersand form when count is null", () => {
    expect(formatAuthors("Smith", "Jones", null)).toBe("Smith & Jones");
  });

  it("returns 'first et al.' when only first is present", () => {
    expect(formatAuthors("Smith", null, 3)).toBe("Smith et al.");
  });

  it("returns last only when only last is present", () => {
    expect(formatAuthors(null, "Jones", 1)).toBe("Jones");
  });
});
