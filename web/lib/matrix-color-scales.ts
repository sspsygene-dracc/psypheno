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

type RGB = [number, number, number];

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
}

// ColorBrewer YlOrRd — the significance ramp (red = most significant).
const YLORRD: Array<[number, RGB]> = [
  [0.0, [255, 255, 204]],
  [0.25, [254, 217, 118]],
  [0.5, [253, 141, 60]],
  [0.75, [240, 59, 32]],
  [1.0, [189, 0, 38]],
];

// Sequential purples — distinct from YlOrRd so an FDR bar reads apart from a p bar.
const PURPLES: Array<[number, RGB]> = [
  [0.0, [252, 251, 253]],
  [0.5, [158, 154, 200]],
  [1.0, [63, 0, 125]],
];

// Diverging blue → white → red (direction of a signed effect).
const BLUE_RED: Array<[number, RGB]> = [
  [0.0, [5, 48, 97]],
  [0.5, [247, 247, 247]],
  [1.0, [103, 0, 31]],
];

// Diverging teal → white → brown (below / above a ratio pivot).
const TEAL_BROWN: Array<[number, RGB]> = [
  [0.0, [1, 102, 94]],
  [0.5, [245, 245, 245]],
  [1.0, [140, 81, 10]],
];

export const COLOR_SCALES: Record<string, ColorScale> = {
  neglog_p: {
    label: "−log10(p)",
    kind: "sequential",
    domain: [1, 20],
    stops: YLORRD,
    note: "red = more significant",
  },
  neglog_q: {
    label: "−log10(FDR)",
    kind: "sequential",
    domain: [1, 20],
    stops: PURPLES,
    note: "purple = more significant",
  },
  signed_neglog_p: {
    label: "signed −log10(p)",
    kind: "diverging",
    domain: [-5, 5],
    mid: 0,
    stops: BLUE_RED,
    note: "blue = down, red = up in mutant",
  },
  activity_ratio: {
    label: "pERK ratio (mut/WT)",
    kind: "diverging",
    domain: [0, 2],
    mid: 1,
    stops: TEAL_BROWN,
    note: "brown = higher, teal = lower than WT",
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

function lerp(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t);
}

/** Map t ∈ [0,1] onto a stop list, returning the interpolated `[r,g,b]`. */
function rampRGB(stops: Array<[number, RGB]>, t: number): RGB {
  const clamped = Math.min(Math.max(t, 0), 1);
  let lo = stops[0];
  let hi = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (clamped >= stops[i][0] && clamped <= stops[i + 1][0]) {
      lo = stops[i];
      hi = stops[i + 1];
      break;
    }
  }
  const span = hi[0] - lo[0] || 1;
  const local = (clamped - lo[0]) / span;
  return [0, 1, 2].map((k) => lerp(lo[1][k], hi[1][k], local)) as unknown as RGB;
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
  return rampRGB(scale.stops, normalize(value, domain, mid, scale.kind === "diverging"));
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
  const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));
  return [fmt(lo), fmt(hi)];
}
