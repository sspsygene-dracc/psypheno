/**
 * Color scales for the cross-modality matrix (#213).
 *
 * Each `metric` id an expanded dataset declares maps to one scale here. The
 * scale owns its colors, kind (sequential / diverging), default domain, and
 * legend label; a dataset may override only the domain (via config → API
 * `meta.metrics`). The matrix colors every cell through `scaleColor` and renders
 * one legend bar per present metric — metrics are never mixed in a single bar.
 *
 * Adding a new metric = add an entry here + name it from a dataset's
 * `overview_matrix_metric` in config.yaml.
 */

import {
  RAMP_BREADTH,
  RAMP_DIRECTION_MUTED,
  RAMP_DIVERGING,
  RAMP_RATIO,
  RAMP_SIGNIFICANCE,
  rampAt,
  type RGB,
} from "@/lib/palette";

export interface ColorScale {
  /** Legend title. */
  label: string;
  kind: "sequential" | "diverging";
  /** [lo, hi] value range the ramp spans. */
  domain: [number, number];
  /** Diverging pivot (defaults to the domain midpoint). */
  mid?: number;
  /** Ramp anchors: position ∈ [0,1] (0 = domain lo, 1 = domain hi) → color. */
  stops: Array<[number, RGB]>;
  /** Short caption under the legend bar. */
  note?: string;
  /**
   * Endpoint formatter for the legend bar. Needed when the stored value isn't
   * the quantity the reader cares about — `sig_readouts` stores log10(1 + n) but
   * the bar has to be labeled in readouts. Defaults to printing the domain.
   */
  legendFormat?: (v: number) => string;
  /**
   * Clustering noise floor: a cell whose distance from the scale's pivot is at
   * or below this carries no signal, and clustering treats it as missing rather
   * than as a value to agree on (see `isInformativeForClustering`). Omit for
   * metrics with no significance semantics — an effect ratio near its pivot is a
   * real measurement, not an absence of one.
   */
  clusterNoiseFloor?: number;
}

// Ramps live in lib/palette.ts: significance (p, FDR) is Greens everywhere on
// the site, breadth (counts / shares of studies) is Purples, direction is RdBu.
export const COLOR_SCALES: Record<string, ColorScale> = {
  neglog_p: {
    label: "−log10(p)",
    kind: "sequential",
    domain: [1, 20],
    stops: RAMP_SIGNIFICANCE,
    note: "darker green = more significant",
    clusterNoiseFloor: 1, // p ≥ 0.1
  },
  neglog_q: {
    // Domain fits the real data: the only neglog_q source today (Binan 2025
    // perturb-FISH) has a permutation floor at q = 0.0099, so -log10(FDR) tops
    // out at 2.0. A wider ramp left every cell in the near-white bottom fifth.
    label: "−log10(FDR)",
    kind: "sequential",
    domain: [1, 2],
    stops: RAMP_SIGNIFICANCE,
    note: "darker green = more significant",
    // Binan 2025 clamps non-hits to exactly q = 0.1, so ~94% of its cells sit on
    // this floor. Left in, they made most row pairs agree perfectly on "nothing
    // happened" and swamped the clustering (see matrix-clustering.ts).
    clusterNoiseFloor: 1, // q ≥ 0.1
  },
  signed_neglog_p: {
    label: "signed −log10(p)",
    kind: "diverging",
    domain: [-5, 5],
    mid: 0,
    stops: RAMP_DIVERGING,
    note: "blue = down, red = up in mutant",
    clusterNoiseFloor: 1, // |signed −log10(p)| ≤ 1 → p ≥ 0.1 in either direction
  },
  sig_readouts: {
    // The summary view's own scale (#234): how many of a dataset's readouts came
    // back significant for a perturbed gene. Stored as log10(1 + n) because the
    // counts span 1 → ~3000 across datasets (a dense DE screen against a
    // 24-parameter behavior panel), and a linear ramp would leave everything but
    // the DE screens pinned at the bottom of the bar. Purples (breadth), so it
    // reads apart from the green p / FDR bars — it isn't a significance value.
    label: "significant readouts",
    kind: "sequential",
    domain: [0, 3.5],
    stops: RAMP_BREADTH,
    note: "log scale; darker = more readouts affected",
    legendFormat: (v) => {
      const n = Math.round(Math.pow(10, v) - 1);
      return n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
    },
    // A gene with zero significant readouts *was* assayed — the cell is real and
    // renders as the palest purple, not as a gap. But for clustering it is the
    // same "nothing here" every other empty cell says, and the widest-coverage
    // dataset is mostly empty: Binan 2025 summarizes 87 of the 90 genes and 63
    // of those are zero. Left in, the only cell most row pairs share is a
    // 0-vs-0 agreement, so unrelated genes look identical and the columns with
    // actual signal (2-15 genes each) never get a say. Same reason `neglog_q`
    // carries a floor.
    clusterNoiseFloor: 0, // no significant readouts
  },
  frac_sig: {
    // Collated view, upper-left triangle: k / n — of the studies that measured
    // a (perturbed gene, readout gene) pair, the share that found it
    // significant. Cells measured by a single study are drawn faded.
    label: "percentage of studies with a significant readout",
    kind: "sequential",
    domain: [0, 1],
    stops: RAMP_BREADTH,
    note: "k of the n studies that measured it; faded = only one study did",
    legendFormat: (v) => `${Math.round(v * 100)}%`,
    clusterNoiseFloor: 0, // no study significant
  },
  direction_agreement: {
    // Collated view, lower-right triangle: (up − down) / k over the significant
    // studies. Grey when no study was significant (no direction to agree on).
    label: "direction agreement",
    kind: "diverging",
    domain: [-1, 1],
    mid: 0,
    stops: RAMP_DIRECTION_MUTED,
    note: "among significant studies; blue = down, red = up",
    legendFormat: (v) => (v < 0 ? "all down" : v > 0 ? "all up" : "mixed"),
  },
  activity_ratio: {
    label: "pERK ratio (mut/WT)",
    kind: "diverging",
    domain: [0, 2],
    mid: 1,
    stops: RAMP_RATIO,
    note: "brown = higher, teal = lower than WT",
    // No clusterNoiseFloor: a ratio at the pivot means "measured, unchanged",
    // which is real evidence — unlike a p-value pinned to its clamp.
  },
};

// Fallback keeps an unknown metric visible instead of blank.
const FALLBACK: ColorScale = {
  label: "value",
  kind: "sequential",
  domain: [0, 1],
  stops: [
    [0, [240, 240, 240]],
    [1, [80, 80, 80]],
  ],
};

export function scaleFor(metric: string): ColorScale {
  return COLOR_SCALES[metric] ?? FALLBACK;
}

/**
 * Does this cell carry signal for clustering?
 *
 * A p/q value pinned to its non-significance clamp says "we looked and found
 * nothing" — every such cell is identical, so treating them as values to agree
 * on makes unrelated rows look like perfect matches. Clustering feeds these
 * through as missing instead (see `matrix-clustering.ts`). Distance from the
 * scale's pivot is what's tested, so a signed metric is judged on |effect| in
 * either direction. Metrics without a `clusterNoiseFloor` are always
 * informative, as is any metric not in the registry.
 */
export function isInformativeForClustering(
  metric: string,
  value: number
): boolean {
  const scale = scaleFor(metric);
  if (scale.clusterNoiseFloor === undefined) return true;
  const pivot = scale.kind === "diverging" ? scale.mid ?? 0 : 0;
  return Math.abs(value - pivot) > scale.clusterNoiseFloor;
}

/** Value → [0,1] ramp coordinate; diverging scales pivot at `mid`. */
function normalize(
  value: number,
  [lo, hi]: [number, number],
  mid: number | undefined,
  diverging: boolean
): number {
  const v = Math.min(Math.max(value, Math.min(lo, hi)), Math.max(lo, hi));
  if (!diverging || mid === undefined) {
    return (v - lo) / (hi - lo || 1);
  }
  if (v <= mid) return 0.5 * ((v - lo) / (mid - lo || 1));
  return 0.5 + 0.5 * ((v - mid) / (hi - mid || 1));
}

/** A value's color as `[r,g,b]` (0–255) — the canvas path uses this directly. */
export function scaleColorRGB(
  metric: string,
  value: number,
  domainOverride?: [number, number] | null
): RGB {
  const scale = scaleFor(metric);
  const domain = domainOverride ?? scale.domain;
  const mid =
    scale.kind === "diverging"
      ? scale.mid ?? (domain[0] + domain[1]) / 2
      : undefined;
  return rampAt(scale.stops, normalize(value, domain, mid, scale.kind === "diverging"));
}

export function scaleColor(
  metric: string,
  value: number,
  domainOverride?: [number, number] | null
): string {
  const [r, g, b] = scaleColorRGB(metric, value, domainOverride);
  return `rgb(${r}, ${g}, ${b})`;
}

/** A `linear-gradient(...)` string for the legend bar of `metric`. */
export function legendGradientCss(
  metric: string,
  domainOverride?: [number, number] | null
): string {
  const scale = scaleFor(metric);
  const stops = scale.stops
    .map(([pos, [r, g, b]]) => `rgb(${r}, ${g}, ${b}) ${(pos * 100).toFixed(0)}%`)
    .join(", ");
  return `linear-gradient(to right, ${stops})`;
}

/** Legend endpoint labels for `metric` (respecting a domain override). */
export function legendEndpoints(
  metric: string,
  domainOverride?: [number, number] | null
): [string, string] {
  const scale = scaleFor(metric);
  const [lo, hi] = domainOverride ?? scale.domain;
  const fmt =
    scale.legendFormat ??
    ((v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1)));
  return [fmt(lo), fmt(hi)];
}
