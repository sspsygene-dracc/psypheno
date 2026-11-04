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
