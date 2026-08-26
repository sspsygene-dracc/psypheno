/**
 * Client-side clustering for the cross-modality matrix (#213).
 *
 * Rows (perturbed genes) and columns (measured genes / phenotypes) can each be
 * reordered so similar profiles sit together. The matrix mixes metrics
 * (−log10 p, signed −log10 p, ratios) and is very sparse, so:
 *
 * - cells pinned to their metric's non-significance clamp are dropped first (see
 *   `isInformativeForClustering`). They are measurements, not gaps, but they are
 *   all the *same* measurement — "we looked and found nothing" — so leaving them
 *   in made unrelated rows agree perfectly and drowned out the real signal;
 * - every column is then min–max normalized to [0,1] over its surviving values,
 *   putting all metrics on one scale (missing cells stay missing);
 * - distance between two rows/cols is the mean absolute difference over the cells
 *   present in *both* (no overlap → the max distance, 1);
 * - ordering is average-linkage hierarchical clustering with a leaf order whose
 *   adjacent merge-endpoints are kept close (a light optimal-leaf-ordering). For
 *   large axes (e.g. columns at K=200) it falls back to greedy nearest-neighbor
 *   seriation so a click never freezes the tab.
 *
 * Everything operates on the *visible* columns the caller passes in, so hidden
 * datasets are excluded from clustering automatically.
 */

import type { MatrixColumn, MatrixGeneRow } from "@/lib/collated-matrix-types";
import { isInformativeForClustering } from "@/lib/matrix-color-scales";

const NO_OVERLAP_DISTANCE = 1;
// Above this many items the O(n^3) agglomerative pass gets switched for O(n^2)
// seriation to stay responsive.
const HCLUST_MAX = 450;

/**
 * rows × cols of per-column min–max normalized values; NaN = missing.
 *
 * Cells at their metric's non-significance clamp are folded into "missing" here,
 * so they neither contribute to a distance nor anchor a column's min–max range.
 */
function normalizedMatrix(
  genes: MatrixGeneRow[],
  columns: MatrixColumn[]
): Float64Array[] {
  const nCols = columns.length;
  const mins = new Float64Array(nCols).fill(Infinity);
  const maxs = new Float64Array(nCols).fill(-Infinity);
  const rows = genes.map((g) => {
    const row = new Float64Array(nCols);
    for (let c = 0; c < nCols; c++) {
      const cell = g.cells[columns[c].key];
      if (
        cell === undefined ||
        !isInformativeForClustering(columns[c].metric, cell.value)
      ) {
        row[c] = NaN;
      } else {
        const v = cell.value;
        row[c] = v;
        if (v < mins[c]) mins[c] = v;
        if (v > maxs[c]) maxs[c] = v;
      }
    }
    return row;
  });
  for (const row of rows) {
    for (let c = 0; c < nCols; c++) {
      const v = row[c];
      if (Number.isNaN(v)) continue;
      const lo = mins[c];
      const hi = maxs[c];
      row[c] = hi > lo ? (v - lo) / (hi - lo) : 0.5;
    }
  }
  return rows;
}

/** Symmetric leaf-distance matrix (flattened) for `n` items via `getVal(item,k)`. */
function distanceMatrix(
  n: number,
  dim: number,
  getVal: (item: number, k: number) => number
): Float64Array {
  const D = new Float64Array(n * n);
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      let sum = 0;
      let count = 0;
      for (let k = 0; k < dim; k++) {
        const a = getVal(i, k);
        const b = getVal(j, k);
        if (Number.isNaN(a) || Number.isNaN(b)) continue;
        sum += Math.abs(a - b);
        count++;
      }
      const d = count > 0 ? sum / count : NO_OVERLAP_DISTANCE;
      D[i * n + j] = d;
      D[j * n + i] = d;
    }
  }
  return D;
}

/** Greedy nearest-neighbor seriation — O(n^2), used for large axes. */
function seriate(n: number, L: Float64Array): number[] {
  if (n <= 1) return n === 1 ? [0] : [];
  const used = new Uint8Array(n);
  const order = [0];
  used[0] = 1;
  let last = 0;
  for (let step = 1; step < n; step++) {
    let best = -1;
    let bestD = Infinity;
    for (let j = 0; j < n; j++) {
      if (used[j]) continue;
      const d = L[last * n + j];
      if (d < bestD) {
        bestD = d;
        best = j;
      }
    }
    used[best] = 1;
    order.push(best);
    last = best;
  }
  return order;
}

/**
 * Average-linkage agglomerative order. Clusters are ordered leaf arrays; each
 * merge orients the two arrays so their touching endpoints are closest (using
 * the leaf distance matrix L). Cluster distances update by Lance–Williams.
 */
function agglomerative(n: number, L: Float64Array): number[] {
  if (n <= 2) return Array.from({ length: n }, (_, i) => i);
  const D = L.slice(); // cluster distances, updated in place
  const size = new Float64Array(n).fill(1);
  const active: number[] = Array.from({ length: n }, (_, i) => i);
  const members: number[][] = Array.from({ length: n }, (_, i) => [i]);

  while (active.length > 1) {
    // Closest active pair.
    let ai = 0;
    let aj = 1;
    let best = Infinity;
    for (let x = 0; x < active.length; x++) {
      const i = active[x];
      for (let y = x + 1; y < active.length; y++) {
        const j = active[y];
        const d = D[i * n + j];
        if (d < best) {
          best = d;
          ai = x;
          aj = y;
        }
      }
    }
    const ci = active[ai];
    const cj = active[aj];
    // Orient the concatenation so the joined endpoints are closest.
    const A = members[ci];
    const B = members[cj];
    const aFirst = A[0];
    const aLast = A[A.length - 1];
    const bFirst = B[0];
    const bLast = B[B.length - 1];
    const opts: Array<[number, number[]]> = [
      [L[aLast * n + bFirst], A.concat(B)],
      [L[aLast * n + bLast], A.concat(B.slice().reverse())],
      [L[aFirst * n + bFirst], A.slice().reverse().concat(B)],
      [L[aFirst * n + bLast], A.slice().reverse().concat(B.slice().reverse())],
    ];
    let merged = opts[0][1];
    let mergedD = opts[0][0];
    for (let o = 1; o < opts.length; o++) {
      if (opts[o][0] < mergedD) {
        mergedD = opts[o][0];
        merged = opts[o][1];
      }
    }
    // Lance–Williams average-linkage update onto ci; drop cj.
    const nI = size[ci];
    const nJ = size[cj];
    for (const k of active) {
      if (k === ci || k === cj) continue;
      const d = (nI * D[ci * n + k] + nJ * D[cj * n + k]) / (nI + nJ);
      D[ci * n + k] = d;
      D[k * n + ci] = d;
    }
    size[ci] = nI + nJ;
    members[ci] = merged;
    active.splice(aj, 1);
  }
  return members[active[0]];
}

function order(n: number, L: Float64Array): number[] {
  return n > HCLUST_MAX ? seriate(n, L) : agglomerative(n, L);
}

/** Row (gene) order: permutation of gene indices. */
export function orderRows(
  genes: MatrixGeneRow[],
  columns: MatrixColumn[]
): number[] {
  const n = genes.length;
  if (n <= 2 || columns.length === 0) {
    return Array.from({ length: n }, (_, i) => i);
  }
  const M = normalizedMatrix(genes, columns);
  const L = distanceMatrix(n, columns.length, (i, k) => M[i][k]);
  return order(n, L);
}

/** Column order: permutation of column indices. */
export function orderColumns(
  genes: MatrixGeneRow[],
  columns: MatrixColumn[]
): number[] {
  const n = columns.length;
  if (n <= 2) return Array.from({ length: n }, (_, i) => i);
  const M = normalizedMatrix(genes, columns);
  const L = distanceMatrix(n, genes.length, (i, k) => M[k][i]);
  return order(n, L);
}
