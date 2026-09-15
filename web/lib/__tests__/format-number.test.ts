import { describe, it, expect } from "vitest";
import { formatCellValue, formatNumber } from "@/lib/format-number";

describe("formatNumber", () => {
  it("renders integers exactly, with no trailing zeros", () => {
    expect(formatNumber(8)).toBe("8");
    expect(formatNumber(107)).toBe("107");
    expect(formatNumber(3227)).toBe("3227");
    expect(formatNumber(1)).toBe("1");
    expect(formatNumber(-42)).toBe("-42");
  });

  it("does not push large integers into lossy exponential form", () => {
    expect(formatNumber(12345)).toBe("12345");
    expect(formatNumber(92791)).toBe("92791");
    // Genomic coordinates are well past the old 1e6 exponential threshold.
    expect(formatNumber(21876000)).toBe("21876000");
  });

  it("renders integral floats (REAL columns with blanks) without padding", () => {
    // An integer column containing any blank is stored as REAL by pandas, so
    // 85 arrives as 85.0 — it should still read as an integer.
    expect(formatNumber(85.0)).toBe("85");
    expect(formatNumber(0.0)).toBe("0");
  });

  it("keeps 4 significant digits for ordinary decimals", () => {
    expect(formatNumber(1.055311776)).toBe("1.055");
    expect(formatNumber(-3.393540217)).toBe("-3.394");
    expect(formatNumber(0.016332763)).toBe("0.01633");
  });

  it("uses exponential notation for very small and very large decimals", () => {
    expect(formatNumber(2.07e-67)).toBe("2.070e-67");
    expect(formatNumber(0.0000123)).toBe("1.230e-5");
    expect(formatNumber(1234567.8)).toBe("1.235e+6");
  });

  it("passes through non-finite values", () => {
    expect(formatNumber(NaN)).toBe("NaN");
    expect(formatNumber(Infinity)).toBe("Infinity");
    expect(formatNumber(-Infinity)).toBe("-Infinity");
  });

  it("falls back to exponential beyond MAX_SAFE_INTEGER", () => {
    expect(formatNumber(1e20)).toBe("1.000e+20");
  });
});

describe("formatCellValue", () => {
  it("renders blanks as empty strings", () => {
    expect(formatCellValue(null)).toBe("");
    expect(formatCellValue(undefined)).toBe("");
  });

  it("formats numbers and stringifies everything else", () => {
    expect(formatCellValue(8)).toBe("8");
    expect(formatCellValue("SHANK3")).toBe("SHANK3");
    expect(formatCellValue(".")).toBe(".");
  });
});
