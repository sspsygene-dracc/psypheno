import { describe, expect, it } from "vitest";
import { descriptionParagraphs, parseInlineMarkup } from "@/lib/inline-markup";

describe("parseInlineMarkup", () => {
  it("leaves plain text alone", () => {
    expect(parseInlineMarkup("no markup here")).toEqual([
      { kind: "text", text: "no markup here" },
    ]);
  });

  it("wraps a **bold** span and keeps the surrounding text", () => {
    expect(
      parseInlineMarkup("before **This is not perturbation data.** after"),
    ).toEqual([
      { kind: "text", text: "before " },
      { kind: "bold", text: "This is not perturbation data." },
      { kind: "text", text: " after" },
    ]);
  });

  it("does not treat an unmatched ** as markup", () => {
    expect(parseInlineMarkup("a ** b")).toEqual([{ kind: "text", text: "a ** b" }]);
  });

  it("does not interpret HTML", () => {
    expect(parseInlineMarkup("<b>nope</b> **yes**")).toEqual([
      { kind: "text", text: "<b>nope</b> " },
      { kind: "bold", text: "yes" },
    ]);
  });
});

describe("descriptionParagraphs", () => {
  it("drops a trailing newline from YAML folded scalars", () => {
    expect(descriptionParagraphs("one paragraph.\n")).toEqual(["one paragraph."]);
  });

  it("splits a blank-line paragraph break", () => {
    expect(descriptionParagraphs("intro.\n**caveat.** rest")).toEqual([
      "intro.",
      "**caveat.** rest",
    ]);
  });
});
