import { describe, expect, it } from "vitest";
import {
  AGREEMENT_COLORS,
  AGREEMENT_NOTHING_TO_COMPARE,
  buildColorGrid,
  cellAgreement,
  CELL_INFERRED,
  CELL_NO_DATA,
  CELL_SHARED,
  CELL_SPLIT,
  CELL_VALUE,
} from "@/lib/matrix-canvas";
import { scaleColorRGB } from "@/lib/matrix-color-scales";
import type { MatrixCell, MatrixColumn, MatrixGeneRow } from "@/lib/collated-matrix-types";

function col(key: string, metric: string): MatrixColumn {
  return {
    section: "s",
    key,
    label: key,
    metric,
    columnIsGene: true,
    nSigGroups: 0,
    sourceTable: "t",
    sourceLabel: "t",
    sourceMediumLabel: null,
    sourceCitation: null,
  };
}

function row(cells: Record<string, MatrixCell>): MatrixGeneRow {
  return { centralGeneId: 1, humanSymbol: "G", cells };
}

const unpack = (c: number) => [(c >> 16) & 255, (c >> 8) & 255, c & 255];

describe("buildColorGrid", () => {
  it("assigns value, inferred and no-data states", () => {
    const grid = buildColorGrid(
      [row({ a: { value: 5 }, b: { value: 0, inferred: "screen" } })],
      [col("a", "neglog_p"), col("b", "neglog_p"), col("c", "neglog_p")],
      {}
    );
    expect(Array.from(grid.state)).toEqual([CELL_VALUE, CELL_INFERRED, CELL_NO_DATA]);
  });

  it("splits a collated cell into share (upper) and direction (lower)", () => {
    const grid = buildColorGrid(
      [row({ a: { value: 1, k: 2, n: 2, nUp: 2, nDown: 0 } })],
      [col("a", "frac_sig")],
      {}
    );
    expect(grid.state[0]).toBe(CELL_SPLIT);
    expect(unpack(grid.packed[0])).toEqual(scaleColorRGB("frac_sig", 1, null));
    expect(unpack(grid.packed2[0])).toEqual(
      scaleColorRGB("direction_agreement", 1, null)
    );
  });

  it("keeps a collated cell one color when no study was significant", () => {
    const grid = buildColorGrid(
      [row({ a: { value: 0, k: 0, n: 3, nUp: 0, nDown: 0 } })],
      [col("a", "frac_sig")],
      {}
    );
    expect(grid.packed[0]).toBe(grid.packed2[0]);
  });

  it("fades a cell measured by a single study toward white", () => {
    const one = buildColorGrid(
      [row({ a: { value: 1, k: 1, n: 1, nUp: 1, nDown: 0 } })],
      [col("a", "frac_sig")],
      {}
    );
    const full = scaleColorRGB("frac_sig", 1, null);
    const faded = unpack(one.packed[0]);
    faded.forEach((channel, i) => expect(channel).toBeGreaterThan(full[i]));
  });

  it("marks a value shared with another study, keeping its color", () => {
    const cols = [col("a", "signed_neglog_p"), col("b", "signed_neglog_p")];
    const grid = buildColorGrid(
      [row({ a: { value: 2, sharedWith: "Other 2026" }, b: { value: 2 } })],
      cols,
      {}
    );
    expect(Array.from(grid.state)).toEqual([CELL_SHARED, CELL_VALUE]);
    expect(grid.packed[0]).toBe(grid.packed[1]);
  });
});

describe("agreement view", () => {
  const lowerOf = (cell: MatrixCell) =>
    unpack(buildColorGrid([row({ a: cell })], [col("a", "frac_sig")], {}, "agreement").packed2[0]);

  it("shows significant studies agreeing in strong purple", () => {
    const cell = { value: 1, k: 2, n: 2, nUp: 2, nDown: 0, nPosAll: 2, nNegAll: 0 };
    expect(cellAgreement(cell)).toEqual({ agreement: "agree", strength: "strong" });
    expect(lowerOf(cell)).toEqual(AGREEMENT_COLORS.strong.agree);
  });

  it("treats significant studies going opposite ways as disagreement", () => {
    expect(lowerOf({ value: 1, k: 2, n: 2, nUp: 1, nDown: 1 })).toEqual(
      AGREEMENT_COLORS.strong.disagree
    );
  });

  it("counts a significant study with no single direction as disagreement", () => {
    // k = 2 but only one study has a direction: the other was mixed.
    expect(cellAgreement({ value: 1, k: 2, n: 2, nUp: 1, nDown: 0 })?.agreement).toBe(
      "disagree"
    );
  });

  it("falls back to effect signs over all studies, in a pale tint", () => {
    // One significant study (down), one n.s. study whose effect points up.
    const cell = { value: 0.5, k: 1, n: 2, nUp: 0, nDown: 1, nPosAll: 1, nNegAll: 1 };
    expect(cellAgreement(cell)).toEqual({ agreement: "disagree", strength: "pale" });
    expect(lowerOf(cell)).toEqual(AGREEMENT_COLORS.pale.disagree);
    expect(lowerOf({ value: 0, k: 0, n: 3, nPosAll: 3, nNegAll: 0 })).toEqual(
      AGREEMENT_COLORS.pale.agree
    );
  });

  it("leaves the tile one color with fewer than two signed studies", () => {
    // Three studies measured it, but two were inferred and have no effect size.
    const cell = { value: 0, k: 0, n: 3, nPosAll: 1, nNegAll: 0 };
    expect(cellAgreement(cell)).toBeNull();
    const grid = buildColorGrid([row({ a: cell })], [col("a", "frac_sig")], {}, "agreement");
    expect(grid.packed[0]).toBe(grid.packed2[0]);
  });

  it("keeps a significant cell split even with nothing to compare", () => {
    // 1 of 2 significant; the other study was inferred, so no second sign.
    const cell = { value: 0.5, k: 1, n: 2, nUp: 1, nDown: 0, nPosAll: 1, nNegAll: 0 };
    expect(cellAgreement(cell)).toBeNull();
    expect(lowerOf(cell)).toEqual(AGREEMENT_NOTHING_TO_COMPARE);
  });

  it("leaves the upper triangle unchanged", () => {
    const cell = { value: 0.5, k: 1, n: 2, nUp: 1, nDown: 0, nPosAll: 2, nNegAll: 0 };
    const direction = buildColorGrid([row({ a: cell })], [col("a", "frac_sig")], {});
    const agreement = buildColorGrid([row({ a: cell })], [col("a", "frac_sig")], {}, "agreement");
    expect(agreement.packed[0]).toBe(direction.packed[0]);
  });
});
