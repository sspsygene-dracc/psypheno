/**
 * "Group columns by" for the /matrix By study view: regroups the columns by a
 * dataset property and lays out the two stacked header band rows — the chosen
 * group on top, the per-dataset bands below.
 *
 * Grouping is per source table (every column of a table lands in the same
 * group), so it needs no overview-DB change: the API sends each table's tags
 * (`CollatedMatrixResponse.datasetGroups`). Group order is fixed per key (the
 * tag vocabulary's own order, untagged last); within a group the columns keep
 * the order the API sent them in (modality, then dataset), so switching the key
 * moves whole datasets around without reshuffling any dataset's columns.
 *
 * Pure functions only — no React, no server imports — so they unit-test cleanly.
 */

import type { MatrixColumn, MatrixDatasetGroups } from "@/lib/collated-matrix-types";
import {
  ANATOMY_REGION_DESCRIPTIONS,
  ANATOMY_REGION_LABELS,
  EXPERIMENT_TYPE_DESCRIPTIONS,
  EXPERIMENT_TYPE_LABELS,
  MODEL_SYSTEM_DESCRIPTIONS,
  MODEL_SYSTEM_LABELS,
  SPECIES_LABELS,
} from "@/lib/dataset-tags";

export type ColumnGroupKey =
  | "modality"
  | "model_system"
  | "region"
  | "species"
  | "experiment_type";

export const COLUMN_GROUP_OPTIONS: ReadonlyArray<{ key: ColumnGroupKey; label: string }> = [
  { key: "modality", label: "Modality" },
  { key: "model_system", label: "Model system" },
  { key: "region", label: "Region" },
  { key: "species", label: "Species" },
  { key: "experiment_type", label: "Experiment type" },
];

export function isColumnGroupKey(v: unknown): v is ColumnGroupKey {
  return COLUMN_GROUP_OPTIONS.some((o) => o.key === v);
}

/** One band of the top header row: a run of columns sharing a group value. */
export interface ColumnGroupBand {
  /** Group value (`NONE_KEY` for untagged); unique within one layout. */
  key: string;
  label: string;
  tooltip: string | null;
  startCol: number;
  span: number;
}

/** One band of the dataset header row (a run of one table's columns). */
export interface DatasetBand {
  gkey: string;
  bandLabel: string;
  sourceTable: string;
  tooltip: string | null;
  span: number;
  startCol: number;
}

/** Group value for a table that has no value for the chosen key. */
export const NONE_KEY = "__none__";

type GroupValue = { key: string; label: string; tooltip: string | null };

/** Display order + labels for a tag vocabulary (the label map's key order). */
interface Vocabulary {
  labels: Record<string, string>;
  descriptions?: Record<string, string>;
  noneLabel: string;
  noneTooltip: string;
}

const VOCABULARIES: Record<Exclude<ColumnGroupKey, "modality">, Vocabulary> = {
  model_system: {
    labels: MODEL_SYSTEM_LABELS,
    descriptions: MODEL_SYSTEM_DESCRIPTIONS,
    noneLabel: "Model system not tagged",
    noneTooltip: "These datasets carry no model_system tag",
  },
  region: {
    labels: ANATOMY_REGION_LABELS,
    descriptions: ANATOMY_REGION_DESCRIPTIONS,
    noneLabel: "No anatomy",
    noneTooltip: "Datasets without anatomy terms (curated resources)",
  },
  species: {
    labels: SPECIES_LABELS,
    noneLabel: "Species unknown",
    noneTooltip: "These datasets name no organism",
  },
  experiment_type: {
    labels: EXPERIMENT_TYPE_LABELS,
    descriptions: EXPERIMENT_TYPE_DESCRIPTIONS,
    noneLabel: "Experiment type not tagged",
    noneTooltip: "These datasets carry no experiment_type tag",
  },
};

function vocabValue(vocab: Vocabulary, raw: string | null): GroupValue {
  if (!raw) return { key: NONE_KEY, label: vocab.noneLabel, tooltip: vocab.noneTooltip };
  return {
    key: raw,
    label: vocab.labels[raw] ?? raw,
    tooltip: vocab.descriptions?.[raw] ?? null,
  };
}

/** Species keys in vocabulary order (unknown keys after, alphabetically). */
function orderSpecies(species: readonly string[]): string[] {
  const order = Object.keys(SPECIES_LABELS);
  const rank = (s: string) => {
    const i = order.indexOf(s);
    return i < 0 ? order.length : i;
  };
  return [...new Set(species)].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

/** The group a column falls in under `key`. */
export function columnGroupValue(
  key: ColumnGroupKey,
  column: MatrixColumn,
  sectionLabel: ReadonlyMap<string, string>,
  datasetGroups: Readonly<Record<string, MatrixDatasetGroups>> | undefined,
): GroupValue {
  if (key === "modality") {
    return {
      key: column.section,
      label: sectionLabel.get(column.section) ?? column.section,
      tooltip: null,
    };
  }
  const g = datasetGroups?.[column.sourceTable];
  if (key === "species") {
    const species = orderSpecies(g?.species ?? []);
    if (species.length === 0) return vocabValue(VOCABULARIES.species, null);
    return {
      key: species.join("+"),
      label: species.map((s) => SPECIES_LABELS[s] ?? s).join(" + "),
      tooltip: null,
    };
  }
  const raw =
    key === "model_system"
      ? (g?.modelSystem ?? null)
      : key === "region"
        ? (g?.region ?? null)
        : (g?.experimentType ?? null);
  return vocabValue(VOCABULARIES[key], raw);
}

/** Sort rank of a group key: vocabulary order, unknown values, untagged last. */
function groupRank(key: ColumnGroupKey, value: string): [number, number] {
  if (value === NONE_KEY) return [2, 0];
  if (key === "species") {
    const order = Object.keys(SPECIES_LABELS);
    const parts = value.split("+");
    const first = order.indexOf(parts[0]);
    // Single species first in vocabulary order; mixes after their first species.
    return first < 0 ? [1, 0] : [0, first * 10 + (parts.length - 1)];
  }
  const order = Object.keys(VOCABULARIES[key as Exclude<ColumnGroupKey, "modality">].labels);
  const i = order.indexOf(value);
  return i < 0 ? [1, 0] : [0, i];
}

/**
 * Reorder `columns` into groups under `key` and lay out the top band row.
 *
 * Modality keeps the API's order (it is already sectioned by modality). Every
 * other key is a stable partition: groups in their fixed order, and inside each
 * group the columns in their incoming order.
 */
export function groupColumns(
  columns: readonly MatrixColumn[],
  key: ColumnGroupKey,
  sectionLabel: ReadonlyMap<string, string>,
  datasetGroups: Readonly<Record<string, MatrixDatasetGroups>> | undefined,
): { columns: MatrixColumn[]; groups: ColumnGroupBand[] } {
  const values = columns.map((c) => columnGroupValue(key, c, sectionLabel, datasetGroups));
  let order = columns.map((_, i) => i);
  if (key !== "modality") {
    const cmpGroup = (a: GroupValue, b: GroupValue) => {
      if (a.key === b.key) return 0;
      const [ta, ra] = groupRank(key, a.key);
      const [tb, rb] = groupRank(key, b.key);
      return ta - tb || ra - rb || a.label.localeCompare(b.label);
    };
    // Array.prototype.sort is stable, so ties (same group) keep incoming order.
    order = order.sort((i, j) => cmpGroup(values[i], values[j]));
  }
  const out = order.map((i) => columns[i]);
  const groups: ColumnGroupBand[] = [];
  order.forEach((i, j) => {
    const v = values[i];
    const last = groups[groups.length - 1];
    if (last && last.key === v.key) {
      last.span++;
      return;
    }
    groups.push({ key: v.key, label: v.label, tooltip: v.tooltip, startCol: j, span: 1 });
  });
  // A modality section split by the API (it never is today) would yield two
  // bands with one key; make keys unique so React keys stay stable.
  const seen = new Map<string, number>();
  for (const g of groups) {
    const n = seen.get(g.key) ?? 0;
    seen.set(g.key, n + 1);
    if (n > 0) g.key = `${g.key}#${n}`;
  }
  return { columns: out, groups };
}

/**
 * The dataset band row: one band per run of a table's columns within one
 * modality. Under modality grouping the modality already heads the band above,
 * so the dataset band shows just the author-year; under any other grouping it
 * keeps today's "modality · author-year".
 */
export function datasetBands(
  columns: readonly MatrixColumn[],
  sectionLabel: ReadonlyMap<string, string>,
  { withModality }: { withModality: boolean },
): DatasetBand[] {
  const bands: DatasetBand[] = [];
  columns.forEach((c, j) => {
    const gkey = `${c.section}|${c.sourceTable}`;
    const last = bands[bands.length - 1];
    if (last && last.gkey.startsWith(`${gkey}@`)) {
      last.span++;
      return;
    }
    const modality = sectionLabel.get(c.section) ?? c.section;
    bands.push({
      // Position-suffixed: the same table can recur after a group boundary
      // only if its columns were split, but keys must stay unique regardless.
      gkey: `${gkey}@${j}`,
      bandLabel: withModality ? `${modality} · ${c.sourceLabel}` : c.sourceLabel,
      sourceTable: c.sourceTable,
      tooltip: [c.sourceMediumLabel ?? c.sourceLabel, c.sourceCitation]
        .filter(Boolean)
        .join(" — "),
      span: 1,
      startCol: j,
    });
  });
  return bands;
}

/**
 * Lines `text` wraps to in a box `perLine` characters wide, by the same greedy
 * word wrapping the browser does. Counting `length / perLine` instead
 * under-counts: "Behavioral · Fernandez Garcia 2026" is 34 characters, but at 10
 * characters per line its unbreakable words leave ragged ends and it takes five
 * lines, not four.
 */
export function wrappedLineCount(text: string, perLine: number): number {
  if (perLine <= 0) return 1;
  let lines = 1;
  let used = 0;
  for (const word of text.split(/\s+/)) {
    if (!word) continue;
    if (used > 0 && used + 1 + word.length > perLine) {
      lines++;
      used = 0;
    }
    if (word.length > perLine) {
      // Longer than the box: breaks mid-word (or overflows, which costs the
      // same height). Rounding up here errs toward a taller band, not a clipped one.
      if (used > 0) {
        lines++;
        used = 0;
      }
      lines += Math.ceil(word.length / perLine) - 1;
      used = word.length % perLine || perLine;
    } else {
      used = used === 0 ? word.length : used + 1 + word.length;
    }
  }
  return lines;
}

/**
 * Height of a band row: tall enough for the band whose label wraps to the most
 * lines at its width, clamped to [minH, maxH].
 */
export function bandRowHeight(
  bands: ReadonlyArray<{ label: string; span: number }>,
  colW: number,
  opts: { chromeW: number; charPx: number; lineH: number; padV: number; minH: number; maxH: number },
): number {
  let maxLines = 1;
  for (const b of bands) {
    const textW = b.span * colW - opts.chromeW;
    const perLine = Math.max(1, Math.floor(textW / opts.charPx));
    maxLines = Math.max(maxLines, wrappedLineCount(b.label, perLine));
  }
  return Math.min(opts.maxH, Math.max(opts.minH, maxLines * opts.lineH + opts.padV));
}
