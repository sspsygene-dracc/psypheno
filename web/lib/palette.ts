/**
 * The site's colour palette: the one place where colours that carry meaning
 * are defined. Neutral greys (body text, borders, stripes) may stay inline;
 * anything that encodes a concept (a tag dimension, a direction, a level of
 * significance, a status) comes from here.
 *
 * Rules:
 *   1. One hue per tag dimension (model system, experiment type, region, ...).
 *   2. Red / blue only for direction of effect (red = up, blue = down).
 *   3. Green only for "significant".
 *   4. Status badges are outlined; concept tags are filled.
 *   5. Muted text no lighter than TEXT.muted (#6b7280, 4.8:1 on white).
 *
 * Everything here is checked for colour-vision deficiencies (protanopia,
 * deuteranopia, tritanopia) and for WCAG AA text contrast by
 * `scripts/check-palette.ts` (run: `npx vite-node scripts/check-palette.ts`);
 * `lib/__tests__/palette.test.ts` runs the same checks in `npm test`.
 */

export type Pill = { color: string; background: string; border?: string };
export type RGB = [number, number, number];
/** Ramp anchors: position ∈ [0,1] → colour. */
export type Ramp = Array<[number, RGB]>;

// ── Tag dimensions (filled pills) ───────────────────────────────────────

export type TagDimension =
  | "modelSystem"
  | "experiment"
  | "region"
  | "stage"
  | "species"
  | "assay";

export const TAG = {
  modelSystem: { color: "#5b21b6", background: "#ede9fe" }, // violet
  experiment: { color: "#115e59", background: "#ccfbf1" }, // teal
  region: { color: "#92400e", background: "#fef3c7" }, // amber
  stage: { color: "#1f2937", background: "#f3f4f6" }, // grey
  species: { color: "#9d174d", background: "#fbcfe8" }, // pink
  assay: { color: "#1e3a8a", background: "#bfdbfe" }, // blue
} as const satisfies Record<TagDimension, Pill>;

/** Dimension names: the legend's labels and the first word of every tooltip. */
export const TAG_NAME: Record<TagDimension, string> = {
  modelSystem: "Model system",
  experiment: "Experiment type",
  region: "Region",
  stage: "Stage",
  species: "Species",
  assay: "Assay",
};

/** Legend tooltips (each starts with the dimension name). */
export const TAG_DESCRIPTION: Record<TagDimension, string> = {
  modelSystem: "Model system: the organism or cell system the data come from (e.g. human brain tissue, organoid, mouse in vivo)",
  experiment: "Experiment type: what kind of study produced the data (perturbation, case vs control, cell-type reference, ...)",
  region: "Region: the brain region (UBERON anatomy term) the data were measured in",
  stage: "Stage: developmental stage or culture age",
  species: "Species: the organism(s) the data come from",
  assay: "Assay: the measurement type of the data table",
};

/** In vitro data: the model-system violet, plus a dashed ring / border. */
export const IN_VITRO = {
  stroke: "#7c3aed",
  dash: "5 3",
  /** White halo under the ring, so it reads on every count fill. */
  halo: "#ffffff",
  fillOnly: "#efe5fe",
  /** Panel / box background for in-vitro groups. */
  tint: "#faf9ff",
  pill: { color: "#5b21b6", background: "#ede9fe", border: "1px dashed #7c3aed" },
} as const;

/** Column-type chips on dataset cards (monospace, square-ish). */
export const COLUMN_TYPE = {
  gene: { color: "#1e3a8a", background: "#dbeafe", border: "1px solid #bfdbfe" },
  numeric: { color: "#334155", background: "#ffffff", border: "1px solid #94a3b8" },
  other: { color: "#374151", background: "#f3f4f6", border: "1px solid #e5e7eb" },
} as const satisfies Record<string, Pill>;

// ── Status badges (outlined, never filled) ──────────────────────────────

export const STATUS = {
  /** Dataset not on the public site (internal / dev only). Expected, not an error. */
  notOnProd: { color: "#92400e", background: "#ffffff", border: "1px solid #f59e0b" },
  /** Paper funded by SSPsyGene. Neutral ink: green is reserved for significance. */
  funded: { color: "#1f2937", background: "#ffffff", border: "1px solid #6b7280" },
  /** "new" on the dataset changelog. */
  isNew: { color: "#1f2937", background: "#ffffff", border: "1px solid #6b7280" },
  /** Perturbation control (NonTarget, GFP, ...) in gene search. */
  control: { color: "#374151", background: "#ffffff", border: "1px dashed #6b7280" },
  /** Paper with links only, no data table. */
  noTable: { color: "#4b5563", background: "#ffffff", border: "1px solid #9ca3af" },
} as const satisfies Record<string, Pill>;

// ── Gene roles (never the direction colours) ────────────────────────────

export const ROLE = {
  perturbed: { color: "#111827", background: "#f8fafc", border: "1px solid #1f2937" },
  measured: { color: "#374151", background: "#f3f4f6", border: "1px solid #e5e7eb" },
} as const satisfies Record<string, Pill>;

/** The perturbed / target gene info panels on gene results: neutral. */
export const ROLE_PANEL = { background: "#f8fafc", border: "#e5e7eb" } as const;

// ── Direction of effect ─────────────────────────────────────────────────

export const DIRECTION = {
  up: "#dc2626",
  down: "#2563eb",
  ns: "#cbd5e1",
  /** The queried gene's dot on the volcano plot (always drawn with the outline). */
  highlight: "#f59e0b",
  highlightOutline: "#111827",
} as const;

/** ColorBrewer RdBu, 11 classes (blue = down, red = up). */
export const RAMP_DIVERGING: Ramp = [
  [0.0, [5, 48, 97]],
  [0.1, [33, 102, 172]],
  [0.2, [67, 147, 195]],
  [0.3, [146, 197, 222]],
  [0.4, [209, 229, 240]],
  [0.5, [247, 247, 247]],
  [0.6, [253, 219, 199]],
  [0.7, [244, 165, 130]],
  [0.8, [214, 96, 77]],
  [0.9, [178, 24, 43]],
  [1.0, [103, 0, 31]],
];

/** Inner tones of RdBu: direction agreement, without the saturated ends. */
export const RAMP_DIRECTION_MUTED: Ramp = [
  [0.0, [67, 147, 195]],
  [0.5, [238, 238, 238]],
  [1.0, [214, 96, 77]],
];

/**
 * Matrix "agreement" view (lower triangle): do the significant studies agree
 * on direction? Dark slate / orange, so it reuses neither the direction
 * blue/red nor the breadth purple that fills the upper triangle.
 */
export const AGREEMENT = {
  agree: [63, 74, 90] as RGB,
  disagree: [230, 97, 1] as RGB,
  nothingToCompare: [196, 200, 207] as RGB,
};

/** ColorBrewer BrBG (teal below / brown above a ratio pivot). */
export const RAMP_RATIO: Ramp = [
  [0.0, [1, 102, 94]],
  [0.5, [245, 245, 245]],
  [1.0, [140, 81, 10]],
];

// ── Significance (green) and breadth (purple) ───────────────────────────

/** Significant rows in data tables: a tint plus a 3px accent bar. */
export const SIGNIFICANT_ROW = { background: "#e8f8ed", accent: "#16a34a" } as const;

/** ColorBrewer Greens: matrix −log10 p and −log10 FDR. */
export const RAMP_SIGNIFICANCE: Ramp = [
  [0.0, [247, 252, 245]],
  [0.25, [199, 233, 192]],
  [0.5, [116, 196, 118]],
  [0.75, [35, 139, 69]],
  [1.0, [0, 68, 27]],
];

/** ColorBrewer Purples: breadth (how many readouts / what share of studies). */
export const RAMP_BREADTH: Ramp = [
  [0.0, [252, 251, 253]],
  [0.25, [203, 201, 226]],
  [0.5, [158, 154, 200]],
  [0.75, [106, 81, 163]],
  [1.0, [63, 0, 125]],
];

// ── /regions coverage map ───────────────────────────────────────────────

/** Fill per bin of tissue-dataset counts (Blues; 0 is neutral grey). */
export const COVERAGE_BINS: ReadonlyArray<{ min: number; label: string; fill: string; ink: string }> = [
  { min: 0, label: "0", fill: "#e1e5ea", ink: "#1f2937" },
  { min: 1, label: "1", fill: "#b6d2ee", ink: "#1f2937" },
  { min: 2, label: "2", fill: "#74a9da", ink: "#1f2937" },
  { min: 3, label: "3–4", fill: "#3b78b8", ink: "#ffffff" },
  { min: 5, label: "5+", fill: "#1c4f8f", ink: "#ffffff" },
];

/** Rings over regions: the open region, and the hovered coarse bucket. */
export const REGION_RING = {
  selected: "#e11d48",
  cover: "#d97706",
} as const;

// ── UI chrome ───────────────────────────────────────────────────────────

export const LINK = { color: "#2563eb", hover: "#1e40af" } as const;

export const TEXT = { body: "#1f2937", secondary: "#4b5563", muted: "#6b7280" } as const;

/** Error text (one-line failures). */
export const ERROR_TEXT = "#b91c1c";

export const BOX = {
  info: { color: "#1e40af", background: "#eff6ff", border: "1px solid #bfdbfe" },
  warning: { color: "#92400e", background: "#fffbeb", border: "1px solid #fcd34d" },
  error: { color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca" },
} as const satisfies Record<string, Pill>;

/** The "on" state of a segmented toggle / chip button. */
export const TOGGLE_ON = { color: "#ffffff", background: "#1f2937" } as const;

/** Nav highlight (header, table of contents). */
export const NAV_ACTIVE = { color: "#1e40af", background: "#eff6ff", bar: "#2563eb" } as const;

// ── helpers ─────────────────────────────────────────────────────────────

export function rgbCss([r, g, b]: RGB): string {
  return `rgb(${r}, ${g}, ${b})`;
}

/** Sample a ramp at t ∈ [0,1] (linear between anchors). */
export function rampAt(stops: Ramp, t: number): RGB {
  const c = Math.min(Math.max(t, 0), 1);
  let lo = stops[0];
  let hi = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (c >= stops[i][0] && c <= stops[i + 1][0]) {
      lo = stops[i];
      hi = stops[i + 1];
      break;
    }
  }
  const span = hi[0] - lo[0] || 1;
  const u = (c - lo[0]) / span;
  return [0, 1, 2].map((k) => Math.round(lo[1][k] + (hi[1][k] - lo[1][k]) * u)) as RGB;
}
