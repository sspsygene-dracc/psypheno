import { describe, expect, it } from "vitest";
import {
  buildColorGrid,
  CELL_INFERRED,
  CELL_NO_DATA,
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
});
