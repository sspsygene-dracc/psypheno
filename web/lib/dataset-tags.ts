// Dataset tags (model system / anatomy / stage) — mirrors
// processing/src/processing/dataset_tags.py. The loader validates the values;
// this module only parses the stored columns and supplies display labels.

// No server imports here: the pages import this module client-side.

export type AnatomyTerm = { id: string; label: string };

export type DatasetTags = {
  model_system: string | null;
  /** UBERON terms in config order. */
  anatomy: AnatomyTerm[];
  /** Tagged ids plus every is_a/part_of ancestor (for region filtering). */
  anatomy_closure: string[];
  anatomy_column: string | null;
  stage: string | null;
  stage_detail: string | null;
};

export const MODEL_SYSTEM_LABELS: Record<string, string> = {
  in_vivo: "In vivo",
  postmortem: "Postmortem",
  organoid: "Organoid",
  primary_culture: "Primary culture",
  ineurons: "iNeurons",
  ipsc_other: "Other iPSC-derived",
  cell_line: "Cell line",
  curated: "Curated resource",
};

export const MODEL_SYSTEM_DESCRIPTIONS: Record<string, string> = {
  in_vivo: "Tissue from a living animal",
  postmortem: "Human postmortem tissue",
  organoid: "Brain organoids / assembloids",
  primary_culture: "Primary cells cultured from tissue",
  ineurons: "iPSC/ESC-derived or directly induced neurons",
  ipsc_other: "Other stem-cell-derived 2D cultures (astrocytes, NPCs, ...)",
  cell_line: "Immortalized cell line",
  curated: "Non-experimental resource: database, genetics study, curated gene list",
};

export const STAGE_LABELS: Record<string, string> = {
  embryonic: "Embryonic",
  fetal: "Fetal",
  postnatal: "Postnatal",
  adult: "Adult",
  larval: "Larval",
  in_vitro: "In vitro",
};

export function modelSystemLabel(key: string): string {
  return MODEL_SYSTEM_LABELS[key] ?? key;
}

export function stageLabel(tags: Pick<DatasetTags, "stage" | "stage_detail">): string | null {
  if (!tags.stage && !tags.stage_detail) return null;
  const base = tags.stage ? (STAGE_LABELS[tags.stage] ?? tags.stage) : null;
  if (base && tags.stage_detail) return `${base} · ${tags.stage_detail}`;
  return base ?? tags.stage_detail;
}

export const EMPTY_TAGS: DatasetTags = {
  model_system: null,
  anatomy: [],
  anatomy_closure: [],
  anatomy_column: null,
  stage: null,
  stage_detail: null,
};

/** The raw DB columns, as selected by `tagSelectSql`. */
export type RawTagColumns = {
  model_system: string | null;
  anatomy: string | null;
  anatomy_closure: string | null;
  anatomy_column?: string | null;
  stage: string | null;
  stage_detail: string | null;
};

const TAG_COLUMNS = [
  "model_system",
  "anatomy",
  "anatomy_closure",
  "anatomy_column",
  "stage",
  "stage_detail",
] as const;

/**
 * SELECT-list fragment for the tag columns, NULL-aliasing any the DB predates
 * (a site between a code deploy and its next load-db) so the route degrades to
 * "no tags" instead of failing at prepare time. `hasColumn` is typically
 * `(c) => columnExists(db, "data_tables", c)`.
 */
export function tagSelectSql(hasColumn: (column: string) => boolean): string {
  return TAG_COLUMNS.map((c) => (hasColumn(c) ? c : `NULL AS ${c}`)).join(", ");
}

export function parseAnatomy(raw: string | null | undefined): AnatomyTerm[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    if (!Array.isArray(v)) return [];
    return v
      .filter(
        (t): t is AnatomyTerm =>
          t && typeof t.id === "string" && typeof t.label === "string",
      )
      .map((t) => ({ id: t.id, label: t.label }));
  } catch {
    return [];
  }
}

function parseIdList(raw: string | null | undefined): string[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function parseTags(r: RawTagColumns): DatasetTags {
  return {
    model_system: r.model_system ?? null,
    anatomy: parseAnatomy(r.anatomy),
    anatomy_closure: parseIdList(r.anatomy_closure),
    anatomy_column: r.anatomy_column ?? null,
    stage: r.stage ?? null,
    stage_detail: r.stage_detail ?? null,
  };
}

/**
 * True when a dataset tagged with `closure` falls under region `regionId`:
 * tagged with that term itself or any subregion / subtype of it.
 */
export function matchesRegion(
  closure: readonly string[] | undefined,
  regionId: string,
): boolean {
  return !!closure && closure.includes(regionId);
}

/**
 * The Region filter's options: a short fixed hierarchy of grouping terms
 * instead of every term in use (20 Brodmann areas, and "multicellular
 * organism", which nearly everything falls under). A grouping term matches a
 * dataset tagged with it or any of its subregions (`anatomy_closure`);
 * `exact` entries match only datasets tagged with that very term. `depth`
 * indents the option.
 */
export const REGION_GROUPS: ReadonlyArray<{
  id: string;
  label: string;
  depth: number;
  exact?: boolean;
}> = [
  { id: "UBERON:0000955", label: "Brain", depth: 0 },
  { id: "UBERON:0001890", label: "Forebrain", depth: 1 },
  { id: "UBERON:0001893", label: "Telencephalon", depth: 2 },
  { id: "UBERON:0000956", label: "Cerebral cortex", depth: 3 },
  { id: "UBERON:0001870", label: "Frontal cortex", depth: 4 },
  { id: "UBERON:0000451", label: "Prefrontal cortex", depth: 5 },
  { id: "UBERON:0016538", label: "Temporal cortex", depth: 4 },
  { id: "UBERON:0001872", label: "Parietal lobe", depth: 4 },
  { id: "UBERON:0002021", label: "Occipital lobe", depth: 4 },
  { id: "UBERON:0003027", label: "Cingulate cortex", depth: 4 },
  { id: "UBERON:0000468", label: "Whole animal", depth: 0, exact: true },
  { id: "UBERON:0002113", label: "Kidney (cell line)", depth: 0, exact: true },
];

/** Region filter value for a REGION_GROUPS entry. */
export function regionFilterValue(group: { id: string; exact?: boolean }): string {
  return group.exact ? `exact:${group.id}` : group.id;
}

/** Does a dataset match a Region filter value (see regionFilterValue)? */
export function matchesRegionFilter(
  tags: { anatomy?: readonly AnatomyTerm[]; anatomy_closure?: readonly string[] },
  value: string,
): boolean {
  if (value.startsWith("exact:")) {
    const id = value.slice("exact:".length);
    return (tags.anatomy ?? []).some((t) => t.id === id);
  }
  return matchesRegion(tags.anatomy_closure, value);
}
