import { describe, it, expect } from "vitest";
import {
  hostFromUrl,
  linkDisplayText,
  parseDatasetLinks,
} from "@/lib/links";

describe("hostFromUrl", () => {
  it("returns hostname for a valid URL", () => {
    expect(hostFromUrl("https://example.com/path")).toBe("example.com");
  });

  it("strips a leading 'www.'", () => {
    expect(hostFromUrl("https://www.example.com/")).toBe("example.com");
  });

  it("returns the input for an invalid URL", () => {
    expect(hostFromUrl("not a url")).toBe("not a url");
  });
});

describe("linkDisplayText", () => {
  it("uses the explicit label when present", () => {
    expect(
      linkDisplayText({ url: "https://example.com", label: "Example" }),
    ).toBe("Example");
  });

  it("falls back to the host derived from the URL", () => {
    expect(linkDisplayText({ url: "https://example.com/path" })).toBe(
      "example.com",
    );
  });
});

describe("parseDatasetLinks", () => {
  it("returns [] for null/undefined/empty input", () => {
    expect(parseDatasetLinks(null)).toEqual([]);
    expect(parseDatasetLinks(undefined)).toEqual([]);
    expect(parseDatasetLinks("")).toEqual([]);
  });

  it("returns [] when JSON is malformed", () => {
    expect(parseDatasetLinks("{not json")).toEqual([]);
  });

  it("returns [] when JSON is not an array", () => {
    expect(parseDatasetLinks('{"url": "x"}')).toEqual([]);
  });

  it("parses an array of valid entries", () => {
    const raw = JSON.stringify([
      { url: "https://a.example/", label: "A", description: "first" },
      { url: "https://b.example/" },
    ]);
    expect(parseDatasetLinks(raw)).toEqual([
      { url: "https://a.example/", label: "A", description: "first" },
      { url: "https://b.example/" },
    ]);
  });

  it("drops entries without a string url", () => {
    const raw = JSON.stringify([
      { url: "https://ok.example/" },
      { url: 42 },
      { url: "" },
      { label: "no url" },
      "not an object",
      null,
    ]);
    expect(parseDatasetLinks(raw)).toEqual([{ url: "https://ok.example/" }]);
  });

  it("drops non-string label/description fields", () => {
    const raw = JSON.stringify([
      { url: "https://x.example/", label: 1, description: false },
    ]);
    expect(parseDatasetLinks(raw)).toEqual([{ url: "https://x.example/" }]);
  });
});
