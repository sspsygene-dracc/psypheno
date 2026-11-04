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
 *    change) into a packed `Uint32Array` (0xRRGGBB) + a per-cell state, indexed
 *    `row * nCols + col`. Scrolling then never recomputes a color.
 *  - `drawCells` — repaint only the visible cell window for the current scroll
 *    offset. Cost ≈ visible cells, independent of how large the matrix is.
 */

import type { MatrixCell, MatrixColumn, MatrixGeneRow } from "@/lib/collated-matrix-types";
import { scaleColorRGB } from "@/lib/matrix-color-scales";

// Cell geometry (shared with CollatedMatrix so the DOM header/labels line up
// with the drawn cells). CELL = tile pitch; GUTTER is the inset on each side, so
// ~2px of the row stripe shows between adjacent tiles (matching the old look).
export const CELL = 17;
export const ROW_H = CELL;
export const COL_W = CELL;
export const GUTTER = 1;
// Column pitch in the summary view (#234). Six dataset columns at COL_W would be
// a 102px ribbon adrift in a 94vw page; row pitch stays put so the gene column
// still lines up.
export const SUMMARY_COL_W = 96;

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
// "Tested, not significant (inferred)" — for sources that published only their
// hits. A flat grey tile with a centred dot: unmistakably a measurement (unlike
// the no-data diagonal) but carrying no value (unlike the color ramps).
export const INFERRED_FILL = "#e9ebef";
export const INFERRED_DOT = "#9ca3af";
const INFERRED_DOT_R = 1.6;
// A value that also appears in another study: a dark corner over the usual color.
export const SHARED_MARK = "#111827";
const SHARED_MARK_SIZE = 5;
const SELECT_OUTLINE = "#111827";

/** Per-cell state in `ColorGrid.state`. */
export const CELL_NO_DATA = 0;
export const CELL_VALUE = 1;
export const CELL_INFERRED = 2;
/** Collated cell: two triangles, `packed` upper-left and `packed2` lower-right. */
export const CELL_SPLIT = 3;
/** A `CELL_VALUE` cell whose value is shared with another study. */
export const CELL_SHARED = 4;

// A collated cell measured by a single study is blended this far toward white:
// "1 of 1" must not read as strong convergence.
const SINGLE_STUDY_FADE = 0.55;
const NO_DIRECTION: [number, number, number] = [226, 228, 232];

export type MetricDomains = Record<string, [number, number] | null>;

/** What a collated cell's lower-right triangle shows. */
export type LowerTriangleMode = "direction" | "agreement";

export type Agreement = "agree" | "disagree";

/**
 * Agreement view colors (purple = agree, orange = disagree; a colorblind-safe
 * pair that doesn't reuse the direction view's blue/red).
 */
export const AGREEMENT_COLORS: Record<Agreement, [number, number, number]> = {
  agree: [94, 60, 153],
  disagree: [230, 97, 1],
};

/**
 * Agreement view: lower triangle of a cell with a significant study but no
 * second significant study to compare it with. Keeps every significant cell
 * split, so the two views read the same way.
 */
export const AGREEMENT_NOTHING_TO_COMPARE: [number, number, number] = [196, 200, 207];

/**
 * Do the significant studies behind a collated cell agree on direction?
 * Needs two or more significant studies: they agree when all of them went the
 * same way; a significant study with no single direction counts as
 * disagreement. Non-significant studies don't take part — the sign of a
 * non-significant effect is close to a coin flip. null: nothing to compare.
 */
export function cellAgreement(cell: MatrixCell): Agreement | null {
  const k = cell.k ?? 0;
  if (k < 2) return null;
  return cell.nUp === k || cell.nDown === k ? "agree" : "disagree";
}

export interface ColorGrid {
  nRows: number;
  nCols: number;
  /** 0xRRGGBB per cell (meaningful where `state[idx]` is CELL_VALUE / CELL_SPLIT). */
  packed: Uint32Array;
  /** Lower-right triangle color for CELL_SPLIT cells. */
  packed2: Uint32Array;
  /** CELL_NO_DATA / CELL_VALUE / CELL_INFERRED. */
  state: Uint8Array;
}

/** Precompute the color of every cell once, in the caller's current row/col order. */
export function buildColorGrid(
  genes: MatrixGeneRow[],
  columns: MatrixColumn[],
  metricDomains: MetricDomains,
  lowerMode: LowerTriangleMode = "direction"
): ColorGrid {
  const nRows = genes.length;
  const nCols = columns.length;
  const packed = new Uint32Array(nRows * nCols);
  const packed2 = new Uint32Array(nRows * nCols);
  const state = new Uint8Array(nRows * nCols);
  const pack = ([r, g, b]: [number, number, number]) => (r << 16) | (g << 8) | b;
  const fade = ([r, g, b]: [number, number, number]): [number, number, number] => [
    Math.round(r + (255 - r) * SINGLE_STUDY_FADE),
    Math.round(g + (255 - g) * SINGLE_STUDY_FADE),
    Math.round(b + (255 - b) * SINGLE_STUDY_FADE),
  ];
  for (let i = 0; i < nRows; i++) {
    const cells = genes[i].cells;
    const base = i * nCols;
    for (let j = 0; j < nCols; j++) {
      const col = columns[j];
      const cell = cells[col.key];
      if (cell === undefined) continue;
      if (cell.inferred !== undefined) {
        state[base + j] = CELL_INFERRED;
        continue;
      }
      if (cell.k !== undefined && cell.n !== undefined) {
        // Collated: upper = % of studies with a significant readout; lower = direction
        // agreement among the significant ones. With k = 0 there is no
        // direction, so the tile stays one color.
        let upper = scaleColorRGB(col.metric, cell.value, metricDomains[col.metric]);
        let lower: [number, number, number] = upper;
        if (lowerMode === "agreement") {
          // A significant cell is always split; with nothing to compare its
          // lower half is neutral grey. Only a cell with no significant study
          // and nothing to compare stays one color.
          const a = cellAgreement(cell);
          if (a) lower = AGREEMENT_COLORS[a];
          else if (cell.k > 0) lower = AGREEMENT_NOTHING_TO_COMPARE;
        } else if (cell.k > 0) {
          const signed = (cell.nUp ?? 0) + (cell.nDown ?? 0);
          lower =
            signed > 0
              ? scaleColorRGB(
                  "direction_agreement",
                  ((cell.nUp ?? 0) - (cell.nDown ?? 0)) / cell.k,
                  null
                )
              : NO_DIRECTION;
        }
        if (cell.n <= 1) {
          upper = fade(upper);
          lower = fade(lower);
        }
        packed[base + j] = pack(upper);
        packed2[base + j] = pack(lower);
        state[base + j] = CELL_SPLIT;
        continue;
      }
      const [r, g, b] = scaleColorRGB(col.metric, cell.value, metricDomains[col.metric]);
      packed[base + j] = (r << 16) | (g << 8) | b;
      state[base + j] = cell.sharedWith !== undefined ? CELL_SHARED : CELL_VALUE;
    }
  }
  return { nRows, nCols, packed, packed2, state };
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
  /** Column pitch; defaults to COL_W (the expanded view's square tiles). */
  colW?: number;
}

/** Repaint the visible cell window onto `ctx`. */
export function drawCells(ctx: CanvasRenderingContext2D, p: DrawParams): void {
  const { grid, scrollLeft, scrollTop, viewW, viewH, dpr, selected } = p;
  const colW = p.colW ?? COL_W;
  const { nRows, nCols, packed, packed2, state } = grid;
  const rgb = (c: number) => `rgb(${(c >> 16) & 255}, ${(c >> 8) & 255}, ${c & 255})`;

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, viewW, viewH);

  const firstRow = Math.max(0, Math.floor(scrollTop / ROW_H));
  const lastRow = Math.min(nRows - 1, Math.floor((scrollTop + viewH) / ROW_H));
  const firstCol = Math.max(0, Math.floor(scrollLeft / colW));
  const lastCol = Math.min(nCols - 1, Math.floor((scrollLeft + viewW) / colW));

  const tileW = colW - 2 * GUTTER;
  const tileH = ROW_H - 2 * GUTTER;

  // No-data diagonals accumulate into one path and get stroked once at the end —
  // a stroke() per tile would cost more than the whole fill pass. Inferred-cell
  // dots and shared-data corners likewise collect into one path each.
  ctx.beginPath();
  const dots = new Path2D();
  const corners = new Path2D();

  for (let i = firstRow; i <= lastRow; i++) {
    const y = i * ROW_H - scrollTop;
    // Row stripe (also the gutter color between tiles in this row).
    ctx.fillStyle = i % 2 === 0 ? ROW_STRIPE_EVEN : ROW_STRIPE_ODD;
    ctx.fillRect(0, y, viewW, ROW_H);

    const base = i * nCols;
    for (let j = firstCol; j <= lastCol; j++) {
      const x = j * colW - scrollLeft;
      const st = state[base + j];
      if (st === CELL_VALUE || st === CELL_SHARED) {
        ctx.fillStyle = rgb(packed[base + j]);
        ctx.fillRect(x + GUTTER, y + GUTTER, tileW, tileH);
        if (st === CELL_SHARED) {
          const xr = x + GUTTER + tileW;
          const yt = y + GUTTER;
          corners.moveTo(xr - SHARED_MARK_SIZE, yt);
          corners.lineTo(xr, yt);
          corners.lineTo(xr, yt + SHARED_MARK_SIZE);
          corners.closePath();
        }
      } else if (st === CELL_SPLIT) {
        const x0 = x + GUTTER;
        const y0 = y + GUTTER;
        const x1 = x0 + tileW;
        const y1 = y0 + tileH;
        const upper = packed[base + j];
        const lower = packed2[base + j];
        ctx.fillStyle = rgb(upper);
        if (upper === lower) {
          ctx.fillRect(x0, y0, tileW, tileH);
        } else {
          const tri = new Path2D();
          tri.moveTo(x0, y0);
          tri.lineTo(x1, y0);
          tri.lineTo(x0, y1);
          tri.closePath();
          ctx.fill(tri);
          const tri2 = new Path2D();
          tri2.moveTo(x1, y0);
          tri2.lineTo(x1, y1);
          tri2.lineTo(x0, y1);
          tri2.closePath();
          ctx.fillStyle = rgb(lower);
          ctx.fill(tri2);
        }
      } else if (st === CELL_INFERRED) {
        ctx.fillStyle = INFERRED_FILL;
        ctx.fillRect(x + GUTTER, y + GUTTER, tileW, tileH);
        const cx = x + colW / 2;
        const cy = y + ROW_H / 2;
        dots.moveTo(cx + INFERRED_DOT_R, cy);
        dots.arc(cx, cy, INFERRED_DOT_R, 0, 2 * Math.PI);
      } else {
        ctx.fillStyle = NO_DATA_FILL;
        ctx.fillRect(x + GUTTER, y + GUTTER, tileW, tileH);
        // Inset a little so adjacent no-data tiles read as separate marks
        // rather than one continuous line across the row.
        ctx.moveTo(x + GUTTER + NO_DATA_INSET, y + GUTTER + NO_DATA_INSET);
        ctx.lineTo(
          x + colW - GUTTER - NO_DATA_INSET,
          y + ROW_H - GUTTER - NO_DATA_INSET
        );
      }
    }
  }

  ctx.strokeStyle = NO_DATA_STROKE;
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.fillStyle = INFERRED_DOT;
  ctx.fill(dots);
  ctx.fillStyle = SHARED_MARK;
  ctx.fill(corners);

  if (
    selected &&
    selected.row >= firstRow &&
    selected.row <= lastRow &&
    selected.col >= firstCol &&
    selected.col <= lastCol
  ) {
    const x = selected.col * colW - scrollLeft;
    const y = selected.row * ROW_H - scrollTop;
    ctx.strokeStyle = SELECT_OUTLINE;
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x + 0.5, y + 0.5, colW - 1, ROW_H - 1);
  }
}

/** Map a pointer offset within the canvas to a cell, or null if out of range. */
export function cellAt(
  offsetX: number,
  offsetY: number,
  scrollLeft: number,
  scrollTop: number,
  nRows: number,
  nCols: number,
  colW: number = COL_W
): { row: number; col: number } | null {
  const col = Math.floor((offsetX + scrollLeft) / colW);
  const row = Math.floor((offsetY + scrollTop) / ROW_H);
  if (row < 0 || row >= nRows || col < 0 || col >= nCols) return null;
  return { row, col };
}
