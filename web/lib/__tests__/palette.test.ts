import { describe, expect, it } from "vitest";
import { contrastRatio, deltaE2000, simulate } from "@/lib/colour-vision";
import { runContrastChecks, runPairChecks } from "@/lib/palette-checks";

describe("colour-vision maths", () => {
  it("computes CIEDE2000 on reference values", () => {
    expect(deltaE2000("#336699", "#336699")).toBeCloseTo(0, 6);
    expect(deltaE2000("#000000", "#ffffff")).toBeCloseTo(100, 0);
    // sRGB red vs green, a commonly quoted reference: 86.61.
    expect(deltaE2000("#ff0000", "#00ff00")).toBeCloseTo(86.61, 1);
  });

  it("WCAG contrast of black on white is 21", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
  });

  it("dichromat simulations collapse red and green, not grey", () => {
    const [r1, g1, b1] = simulate("#808080", "deuteranopia");
    expect(Math.abs(r1 - 128) + Math.abs(g1 - 128) + Math.abs(b1 - 128)).toBeLessThan(3);
    // Pure red and a matching green look alike to a deuteranope.
    expect(deltaE2000(simulate("#d62728", "deuteranopia"), simulate("#8c8c00", "deuteranopia"))).toBeLessThan(
      deltaE2000("#d62728", "#8c8c00"),
    );
  });
});

describe("palette", () => {
  it("keeps every must-differ pair apart under all colour-vision simulations", () => {
    const failed = runPairChecks()
      .filter((r) => !r.ok)
      .map((r) => `${r.category}: ${r.name} (worst ΔE ${r.worst.toFixed(1)})`);
    expect(failed).toEqual([]);
  });

  it("meets WCAG AA for every text/background pair", () => {
    const failed = runContrastChecks()
      .filter((c) => !c.ok)
      .map((c) => `${c.name}: ${c.ratio.toFixed(2)}:1`);
    expect(failed).toEqual([]);
  });
});
