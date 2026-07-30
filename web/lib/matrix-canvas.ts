/**
 * Canvas cell rendering for the cross-modality matrix (#213).
 *
 * The heatmap's cell field is a sea of colored rectangles — one styled `<td>`
 * per cell doesn't scroll past a few thousand nodes. So we draw the cells on a
 * single `<canvas>`: the DOM keeps only the header, the frozen gene column, and
 * the legends (the parts that need text / links / hit targets). This module owns
 * the two pure pieces:
 *
 *  - `buildColorGrid` — precompute every cell's color once (per data/order
 *    change) into a packed `Uint32Array` (0xRRGGBB) + a present-mask, indexed
 *    `row * nCols + col`. Scrolling then never recomputes a color.
 *  - `drawCells` — repaint only the visible cell window for the current scroll
 *    offset. Cost ≈ visible cells, independent of how large the matrix is.
 */

import type { MatrixColumn, MatrixGeneRow } from "@/lib/collated-matrix-types";
import { scaleColorRGB } from "@/lib/matrix-color-scales";

// Cell geometry (shared with CollatedMatrix so the DOM header/labels line up
// with the drawn cells). CELL = tile pitch; GUTTER is the inset on each side, so
// ~2px of the row stripe shows between adjacent tiles (matching the old look).
export const CELL = 17;
export const ROW_H = CELL;
export const COL_W = CELL;
export const GUTTER = 1;

// Row stripes (the gutter color) + the no-data tile fill — kept identical to the
// previous DOM rendering.
export const ROW_STRIPE_EVEN = "#ffffff";
export const ROW_STRIPE_ODD = "#fafbfc";
export const NO_DATA_FILL = "#fcfcfd";
// A no-data tile is near-white, and so is the bottom of a sequential ramp — a
// measurement clamped to "not significant" rendered all but identically to an
// absent one. The diagonal marks absence so the two read apart at a glance.
export const NO_DATA_STROKE = "#ecedf0";
// Keeps each diagonal clear of the tile corners, so a run of no-data tiles reads
// as separate ticks instead of one unbroken line.
const NO_DATA_INSET = 3;
const SELECT_OUTLINE = "#111827";

export type MetricDomains = Record<string, [number, number] | null>;

export interface ColorGrid {
  nRows: number;
  nCols: number;
  /** 0xRRGGBB per cell (only meaningful where `present[idx]` is 1). */
  packed: Uint32Array;
  /** 1 = the cell has data, 0 = no data. */
  present: Uint8Array;
}

/** Precompute the color of every cell once, in the caller's current row/col order. */
export function buildColorGrid(
  genes: MatrixGeneRow[],
  columns: MatrixColumn[],
  metricDomains: MetricDomains
): ColorGrid {
  const nRows = genes.length;
  const nCols = columns.length;
  const packed = new Uint32Array(nRows * nCols);
  const present = new Uint8Array(nRows * nCols);
  for (let i = 0; i < nRows; i++) {
    const cells = genes[i].cells;
    const base = i * nCols;
    for (let j = 0; j < nCols; j++) {
      const col = columns[j];
      const cell = cells[col.key];
      if (cell === undefined) continue;
      const [r, g, b] = scaleColorRGB(col.metric, cell.value, metricDomains[col.metric]);
      packed[base + j] = (r << 16) | (g << 8) | b;
      present[base + j] = 1;
    }
  }
  return { nRows, nCols, packed, present };
}

export interface DrawParams {
  grid: ColorGrid;
  /** Scroll offset of the body viewport, in content px. */
  scrollLeft: number;
  scrollTop: number;
  /** Canvas CSS size (client box of the body scroller). */
  viewW: number;
  viewH: number;
  dpr: number;
  /** Currently click-selected cell (drawn with an outline), or null. */
  selected: { row: number; col: number } | null;
}

/** Repaint the visible cell window onto `ctx`. */
export function drawCells(ctx: CanvasRenderingContext2D, p: DrawParams): void {
  const { grid, scrollLeft, scrollTop, viewW, viewH, dpr, selected } = p;
  const { nRows, nCols, packed, present } = grid;

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, viewW, viewH);

  const firstRow = Math.max(0, Math.floor(scrollTop / ROW_H));
  const lastRow = Math.min(nRows - 1, Math.floor((scrollTop + viewH) / ROW_H));
  const firstCol = Math.max(0, Math.floor(scrollLeft / COL_W));
  const lastCol = Math.min(nCols - 1, Math.floor((scrollLeft + viewW) / COL_W));

  const tileW = COL_W - 2 * GUTTER;
  const tileH = ROW_H - 2 * GUTTER;

  // No-data diagonals accumulate into one path and get stroked once at the end —
  // a stroke() per tile would cost more than the whole fill pass.
  ctx.beginPath();

  for (let i = firstRow; i <= lastRow; i++) {
    const y = i * ROW_H - scrollTop;
    // Row stripe (also the gutter color between tiles in this row).
    ctx.fillStyle = i % 2 === 0 ? ROW_STRIPE_EVEN : ROW_STRIPE_ODD;
    ctx.fillRect(0, y, viewW, ROW_H);

    const base = i * nCols;
    for (let j = firstCol; j <= lastCol; j++) {
      const x = j * COL_W - scrollLeft;
      if (present[base + j]) {
        const c = packed[base + j];
        ctx.fillStyle = `rgb(${(c >> 16) & 255}, ${(c >> 8) & 255}, ${c & 255})`;
        ctx.fillRect(x + GUTTER, y + GUTTER, tileW, tileH);
      } else {
        ctx.fillStyle = NO_DATA_FILL;
        ctx.fillRect(x + GUTTER, y + GUTTER, tileW, tileH);
        // Inset a little so adjacent no-data tiles read as separate marks
        // rather than one continuous line across the row.
        ctx.moveTo(x + GUTTER + NO_DATA_INSET, y + GUTTER + NO_DATA_INSET);
        ctx.lineTo(
          x + COL_W - GUTTER - NO_DATA_INSET,
          y + ROW_H - GUTTER - NO_DATA_INSET
        );
      }
    }
  }

  ctx.strokeStyle = NO_DATA_STROKE;
  ctx.lineWidth = 1;
  ctx.stroke();

  if (
    selected &&
    selected.row >= firstRow &&
    selected.row <= lastRow &&
    selected.col >= firstCol &&
    selected.col <= lastCol
  ) {
    const x = selected.col * COL_W - scrollLeft;
    const y = selected.row * ROW_H - scrollTop;
    ctx.strokeStyle = SELECT_OUTLINE;
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x + 0.5, y + 0.5, COL_W - 1, ROW_H - 1);
  }
}

/** Map a pointer offset within the canvas to a cell, or null if out of range. */
export function cellAt(
  offsetX: number,
  offsetY: number,
  scrollLeft: number,
  scrollTop: number,
  nRows: number,
  nCols: number
): { row: number; col: number } | null {
  const col = Math.floor((offsetX + scrollLeft) / COL_W);
  const row = Math.floor((offsetY + scrollTop) / ROW_H);
  if (row < 0 || row >= nRows || col < 0 || col >= nCols) return null;
  return { row, col };
}
