/**
 * The colour pairs the palette must keep apart, and the text/background pairs
 * that must meet WCAG AA. Shared by scripts/check-palette.ts (prints a report)
 * and lib/__tests__/palette.test.ts (fails the build on a regression).
 */
import {
  VISIONS,
  contrastRatio,
  deltaEUnder,
  type RGB,
  type Vision,
} from "./colour-vision";
import {
  BOX,
  COVERAGE_BINS,
  DIRECTION,
  ERROR_TEXT,
  IN_VITRO,
  LINK,
  NAV_ACTIVE,
  RAMP_BREADTH,
  RAMP_DIRECTION_MUTED,
  RAMP_DIVERGING,
  RAMP_RATIO,
  RAMP_SIGNIFICANCE,
  REGION_RING,
  ROLE,
  SIGNIFICANT_ROW,
  STATUS,
  TAG,
  TAG_NAME,
  TEXT,
  TOGGLE_ON,
  rampAt,
  type Pill,
  type Ramp,
  type TagDimension,
} from "./palette";

type Colour = string | RGB;

export type PairCheck = {
  category: string;
  name: string;
  a: Colour;
  b: Colour;
  /** Minimum ΔE2000 required under every simulation. */
  min: number;
  /**
   * Pills only: the label colours. A pill pair passes when, under every
   * simulation, the fills differ by `min` OR the label colours by TEXT_MIN.
   */
  text?: [Colour, Colour];
};

export type PairResult = PairCheck & {
  dE: Record<Vision, number>;
  textDE?: Record<Vision, number>;
  worst: number;
  ok: boolean;
};

const WHITE = "#ffffff";

/** ΔE threshold for data marks (dots, cells, fills). */
export const DATA_MIN = 10;
/** Pills carry their label in text, so hue only has to keep dimensions apart. */
export const PILL_MIN = 5;
/** ...or, failing that, their label colours must differ by this much. */
export const TEXT_MIN = 10;

function rampSteps(category: string, label: string, ramp: Ramp, n = 5): PairCheck[] {
  const out: PairCheck[] = [];
  for (let i = 0; i < n - 1; i++) {
    const t0 = i / (n - 1), t1 = (i + 1) / (n - 1);
    out.push({
      category,
      name: `${label} step ${t0.toFixed(2)} vs ${t1.toFixed(2)}`,
      a: rampAt(ramp, t0),
      b: rampAt(ramp, t1),
      min: DATA_MIN,
    });
  }
  return out;
}

function divergingEnds(category: string, label: string, ramp: Ramp): PairCheck[] {
  const lo = rampAt(ramp, 0), mid = rampAt(ramp, 0.5), hi = rampAt(ramp, 1);
  return [
    { category, name: `${label}: down end vs middle`, a: lo, b: mid, min: DATA_MIN },
    { category, name: `${label}: up end vs middle`, a: hi, b: mid, min: DATA_MIN },
    { category, name: `${label}: down end vs up end`, a: lo, b: hi, min: DATA_MIN },
    // A quarter of the way out still has to read as a direction.
    { category, name: `${label}: down 0.25 vs up 0.75`, a: rampAt(ramp, 0.25), b: rampAt(ramp, 0.75), min: DATA_MIN },
  ];
}

export function pairChecks(): PairCheck[] {
  const checks: PairCheck[] = [];
  const add = (category: string, name: string, a: Colour, b: Colour, min = DATA_MIN) =>
    checks.push({ category, name, a, b, min });

  // Direction: volcano dots.
  add("direction", "volcano up vs down", DIRECTION.up, DIRECTION.down);
  add("direction", "volcano up vs n.s.", DIRECTION.up, DIRECTION.ns);
  add("direction", "volcano down vs n.s.", DIRECTION.down, DIRECTION.ns);
  add("direction", "volcano query gene vs up", DIRECTION.highlight, DIRECTION.up);
  add("direction", "volcano query gene vs down", DIRECTION.highlight, DIRECTION.down);
  add("direction", "volcano query gene vs n.s.", DIRECTION.highlight, DIRECTION.ns);
  checks.push(...divergingEnds("direction", "RdBu", RAMP_DIVERGING));
  checks.push(...divergingEnds("direction", "muted RdBu", RAMP_DIRECTION_MUTED));
  checks.push(...divergingEnds("direction", "BrBG ratio", RAMP_RATIO));

  // Ramps.
  checks.push(...rampSteps("significance ramp", "Greens", RAMP_SIGNIFICANCE));
  checks.push(...rampSteps("breadth ramp", "Purples", RAMP_BREADTH));
  // The collated matrix puts breadth (upper triangle) next to direction
  // agreement (lower triangle): a dark purple must not pass for "down".
  // Informational (min 0): the two sit in opposite triangles of a cell, each
  // with its own legend, so position tells them apart. Under protanopia a
  // mid purple and the muted "all down" blue are close (see the report).
  for (const t of [0.5, 0.75, 1]) {
    add("breadth ramp", `Purples ${t} vs direction "all down" (info)`, rampAt(RAMP_BREADTH, t), rampAt(RAMP_DIRECTION_MUTED, 0), 0);
  }
  // Significance next to breadth (summary columns sit beside p-value columns).
  for (const t of [0.5, 0.75, 1]) {
    add("breadth ramp", `Greens ${t} vs Purples ${t}`, rampAt(RAMP_SIGNIFICANCE, t), rampAt(RAMP_BREADTH, t));
  }

  // Coverage bins (/regions map).
  for (let i = 0; i < COVERAGE_BINS.length - 1; i++) {
    const a = COVERAGE_BINS[i], b = COVERAGE_BINS[i + 1];
    add("coverage bins", `bin ${a.label} vs ${b.label}`, a.fill, b.fill);
  }
  // In-vitro-only regions are marked by the dashed violet ring (checked below
  // against every fill); the pale fill is a secondary cue. No pale fill can
  // clear 10 against both bin 0 and bin 1 under every simulation (best found:
  // ~6), so the fill is held to the pill bar.
  add("coverage bins", "in-vitro-only fill vs bin 0", IN_VITRO.fillOnly, COVERAGE_BINS[0].fill, PILL_MIN);
  add("coverage bins", "in-vitro-only fill vs bin 1", IN_VITRO.fillOnly, COVERAGE_BINS[1].fill, PILL_MIN);
  add("coverage bins", "selected ring vs cover ring", REGION_RING.selected, REGION_RING.cover);
  add("coverage bins", "selected ring vs in-vitro ring", REGION_RING.selected, IN_VITRO.stroke);
  add("coverage bins", "cover ring vs in-vitro ring", REGION_RING.cover, IN_VITRO.stroke);
  for (const bin of COVERAGE_BINS) {
    add("coverage bins", `selected ring on bin ${bin.label}`, REGION_RING.selected, bin.fill);
  }
  // The in-vitro ring is drawn over a white halo, so it reads on any fill.
  add("coverage bins", "in-vitro ring vs its halo", IN_VITRO.stroke, IN_VITRO.halo);
  add("coverage bins", "in-vitro halo on bin 5+", IN_VITRO.halo, COVERAGE_BINS[COVERAGE_BINS.length - 1].fill);

  // Significant rows.
  add("significant row", "accent bar vs plain row", SIGNIFICANT_ROW.accent, WHITE);
  // The tint is a secondary cue (the bar carries the meaning); it only has to
  // be visible, so it's held to a lower bar.
  add("significant row", "tint vs plain row", SIGNIFICANT_ROW.background, WHITE, 3);

  // Tag dimensions, every pair: fill, or failing that the label colour.
  const dims = Object.keys(TAG) as TagDimension[];
  const pill = (name: string, a: Pill, b: Pill) =>
    checks.push({ category: "tags", name, a: a.background, b: b.background, min: PILL_MIN, text: [a.color, b.color] });
  for (let i = 0; i < dims.length; i++) {
    for (let j = i + 1; j < dims.length; j++) {
      pill(`${TAG_NAME[dims[i]]} vs ${TAG_NAME[dims[j]]}`, TAG[dims[i]], TAG[dims[j]]);
    }
  }
  // In vitro is a model system and shares its colours (plus a dashed border),
  // so it needs no pair of its own.

  // Status badges are white with an outline; tags are filled with no outline.
  // What tells them apart is the badge's outline against the tag's fill.
  for (const [sk, s] of Object.entries(STATUS)) {
    for (const d of dims) {
      add("status vs tags", `${sk} outline vs ${TAG_NAME[d]} fill`, borderColour(s), TAG[d].background, DATA_MIN);
    }
  }
  add("status vs tags", "notOnProd outline vs funded outline", borderColour(STATUS.notOnProd), borderColour(STATUS.funded), DATA_MIN);
  add("status vs tags", "perturbed role outline vs measured role outline", borderColour(ROLE.perturbed), borderColour(ROLE.measured), DATA_MIN);

  return checks;
}

function borderColour(p: Pill): string {
  const m = /#[0-9a-fA-F]{3,6}/.exec(p.border ?? "");
  return m ? m[0] : p.background;
}

export function runPairChecks(): PairResult[] {
  return pairChecks().map((c) => {
    const dE = Object.fromEntries(VISIONS.map((v) => [v, deltaEUnder(c.a, c.b, v)])) as Record<Vision, number>;
    const worst = Math.min(...VISIONS.map((v) => dE[v]));
    if (!c.text) return { ...c, dE, worst, ok: worst >= c.min };
    const [ta, tb] = c.text;
    const textDE = Object.fromEntries(VISIONS.map((v) => [v, deltaEUnder(ta, tb, v)])) as Record<Vision, number>;
    const ok = VISIONS.every((v) => dE[v] >= c.min || textDE[v] >= TEXT_MIN);
    return { ...c, dE, textDE, worst, ok };
  });
}

export type ContrastCheck = { name: string; fg: string; bg: string; ratio: number; min: number; ok: boolean };

export function runContrastChecks(): ContrastCheck[] {
  const pairs: Array<[string, string, string, number?]> = [];
  for (const d of Object.keys(TAG) as TagDimension[]) {
    pairs.push([`tag ${TAG_NAME[d]}`, TAG[d].color, TAG[d].background]);
  }
  pairs.push(["in-vitro pill", IN_VITRO.pill.color, IN_VITRO.pill.background]);
  pairs.push(["in-vitro group heading", IN_VITRO.pill.color, IN_VITRO.tint]);
  for (const [k, s] of Object.entries(STATUS)) pairs.push([`status ${k}`, s.color, s.background]);
  for (const [k, s] of Object.entries(ROLE)) pairs.push([`role ${k}`, s.color, s.background]);
  for (const [k, s] of Object.entries(BOX)) {
    pairs.push([`box ${k}`, s.color, s.background]);
    pairs.push([`box ${k}: link`, LINK.hover, s.background]);
  }
  pairs.push(["link on white", LINK.color, WHITE]);
  pairs.push(["link on significant row", LINK.color, SIGNIFICANT_ROW.background]);
  pairs.push(["link hover on white", LINK.hover, WHITE]);
  pairs.push(["nav active", NAV_ACTIVE.color, NAV_ACTIVE.background]);
  pairs.push(["body text", TEXT.body, WHITE]);
  pairs.push(["secondary text", TEXT.secondary, WHITE]);
  pairs.push(["muted text on white", TEXT.muted, WHITE]);
  pairs.push(["body text on significant row", TEXT.body, SIGNIFICANT_ROW.background]);
  pairs.push(["error text", ERROR_TEXT, WHITE]);
  pairs.push(["toggle on", TOGGLE_ON.color, TOGGLE_ON.background]);
  for (const b of COVERAGE_BINS) pairs.push([`region label on bin ${b.label}`, b.ink, b.fill]);
  pairs.push(["region label on in-vitro-only fill", TEXT.body, IN_VITRO.fillOnly]);
  // Non-text UI marks: WCAG 1.4.11 asks 3:1.
  pairs.push(["significant-row accent bar (non-text)", SIGNIFICANT_ROW.accent, WHITE, 3]);
  pairs.push(["volcano up dot (non-text)", DIRECTION.up, WHITE, 3]);
  pairs.push(["volcano down dot (non-text)", DIRECTION.down, WHITE, 3]);
  return pairs.map(([name, fg, bg, min = 4.5]) => {
    const ratio = contrastRatio(fg, bg);
    return { name, fg, bg, ratio, min, ok: ratio >= min };
  });
}
