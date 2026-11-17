// Dataset tags (model system / anatomy / stage) — mirrors
// processing/src/processing/dataset_tags.py. The loader validates the values;
// this module only parses the stored columns and supplies display labels.

// No server imports here: the pages import this module client-side.

import { closureHits } from "@/lib/brain-regions";

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
  /** dataset_tags EXPERIMENT_TYPES key (how the genes were perturbed, if at all). */
  experiment_type: string | null;
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

/**
 * `experiment_type` values (dataset_tags.EXPERIMENT_TYPES), in display order:
 * how the genes were perturbed, or what kind of study it is.
 */
export const EXPERIMENT_TYPE_LABELS: Record<string, string> = {
  crispr_ko: "CRISPR knockout",
  crispri: "CRISPRi",
  crispra: "CRISPRa",
  knockdown: "RNAi / ASO knockdown",
  overexpression: "Overexpression",
  isogenic_variant: "Engineered variant",
  patient_lines: "Patient-derived lines",
  drug_treatment: "Drug treatment",
  multiple: "Several perturbation types",
  observational: "Observational",
  human_genetics: "Human genetics",
  curated: "Curated resource",
  other: "Other",
};

export const EXPERIMENT_TYPE_DESCRIPTIONS: Record<string, string> = {
  crispr_ko:
    "Cas9 knockout / loss-of-function edits: pooled CRISPR-KO screens, in vivo Perturb-seq, KO lines, mutant and crispant zebrafish",
  crispri: "CRISPR interference (dCas9-KRAB)",
  crispra: "CRISPR activation",
  knockdown: "RNAi (shRNA / siRNA) or antisense-oligo knockdown",
  overexpression: "Exogenous expression of a wild-type gene, e.g. tagged AP-MS baits",
  isogenic_variant: "Engineered disease variant vs the wild-type allele in the same background",
  patient_lines: "Patient-derived iPSCs / neurons / organoids vs control lines",
  drug_treatment: "Pharmacological treatment",
  multiple: "One table combining several perturbation types",
  observational: "No manipulation: postmortem case vs control, markers, inferred networks",
  human_genetics: "Association statistics from human sequencing cohorts",
  curated: "Databases and curated gene lists",
  other: "Other experiment type",
};

export function experimentTypeLabel(key: string): string {
  return EXPERIMENT_TYPE_LABELS[key] ?? key;
}

/**
 * Coarse anatomical regions (`data_tables.anatomy_region`, derived by
 * DatasetTags.coarse_region in dataset_tags.py), in display order. A table is
 * assigned the first region that covers *all* of its UBERON terms.
 */
export const ANATOMY_REGION_LABELS: Record<string, string> = {
  cerebral_cortex: "Cerebral cortex",
  forebrain: "Other forebrain",
  brain: "Brain (whole or unspecified)",
  whole_organism: "Whole organism",
};

export const ANATOMY_REGION_DESCRIPTIONS: Record<string, string> = {
  cerebral_cortex: "All anatomy terms in the cerebral cortex or a cerebral lobe",
  forebrain: "All terms in the forebrain, not all in the cortex (e.g. telencephalon)",
  brain: "All terms in the brain, not all in the forebrain — incl. whole brain",
  whole_organism: "Whole animal (e.g. zebrafish larva behavior)",
};

/** Organism keys (globals.yaml `organismTypes`), in display order. */
export const SPECIES_LABELS: Record<string, string> = {
  human: "Human",
  mouse: "Mouse",
  zebrafish: "Zebrafish",
};

/**
 * The organism(s) a table's experiment was done in: its organism_key list, or
 * the gene species when that is empty. Not gene_species alone — zebrafish
 * screens key their genes by human ortholog, so their gene_species is human.
 */
export function datasetOrganisms(d: {
  organism_key?: readonly string[] | null;
  gene_species?: string | null;
}): string[] {
  const keys = d.organism_key ?? [];
  if (keys.length > 0) return [...keys];
  return d.gene_species ? [d.gene_species] : [];
}

/** Organism keys in SPECIES_LABELS order, unknown keys after, alphabetically. */
export function sortSpecies(keys: Iterable<string>): string[] {
  const order = Object.keys(SPECIES_LABELS);
  const rank = (s: string) => {
    const i = order.indexOf(s);
    return i < 0 ? order.length : i;
  };
  return [...new Set(keys)].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

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
  experiment_type: null,
};

/** The raw DB columns, as selected by `tagSelectSql`. */
export type RawTagColumns = {
  model_system: string | null;
  anatomy: string | null;
  anatomy_closure: string | null;
  anatomy_column?: string | null;
  stage: string | null;
  stage_detail: string | null;
  experiment_type?: string | null;
};

const TAG_COLUMNS = [
  "model_system",
  "anatomy",
  "anatomy_closure",
  "anatomy_column",
  "stage",
  "stage_detail",
  "experiment_type",
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

/**
 * Display labels that replace the stored UBERON label — mirrors
 * ANATOMY_LABEL_OVERRIDES in dataset_tags.py, applied here too so a DB built
 * before the override reads the same.
 */
export const ANATOMY_LABEL_OVERRIDES: Readonly<Record<string, string>> = {
  "UBERON:0000955": "Whole brain",
};

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
      .map((t) => ({ id: t.id, label: ANATOMY_LABEL_OVERRIDES[t.id] ?? t.label }));
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
    experiment_type: r.experiment_type ?? null,
  };
}

/**
 * True when a dataset tagged with `closure` falls under region `regionId`:
 * tagged with that term itself or any subregion / subtype of it — including
 * the Brodmann areas UBERON fails to file under their lobe, which
 * CURATED_PART_OF (lib/brain-regions.ts) adds by hand.
 */
export function matchesRegion(
  closure: readonly string[] | undefined,
  regionId: string,
): boolean {
  return closureHits(closure, regionId);
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
  { id: "UBERON:0000955", label: "Any brain region", depth: 0 },
  { id: "UBERON:0001890", label: "Forebrain", depth: 1 },
  { id: "UBERON:0001893", label: "Telencephalon", depth: 2 },
  { id: "UBERON:0000956", label: "Cerebral cortex", depth: 3 },
  { id: "UBERON:0001870", label: "Frontal cortex", depth: 4 },
  { id: "UBERON:0000451", label: "Prefrontal cortex", depth: 5 },
  { id: "UBERON:0016538", label: "Temporal cortex", depth: 4 },
  { id: "UBERON:0001872", label: "Parietal lobe", depth: 4 },
  { id: "UBERON:0002021", label: "Occipital lobe", depth: 4 },
  { id: "UBERON:0003027", label: "Cingulate cortex", depth: 4 },
  // Structures the /regions drawings show (lib/brain-regions.ts filterGroup),
  // so a region there can link here. Options nothing is tagged with are
  // hidden in the filter, so these cost nothing until a dataset uses them.
  { id: "UBERON:0002022", label: "Insula", depth: 4 },
  { id: "UBERON:0002421", label: "Hippocampal formation", depth: 4 },
  { id: "UBERON:0002264", label: "Olfactory bulb", depth: 3 },
  { id: "UBERON:0002435", label: "Striatum", depth: 3 },
  { id: "UBERON:0001897", label: "Thalamus", depth: 2 },
  { id: "UBERON:0001898", label: "Hypothalamus", depth: 2 },
  { id: "UBERON:0001891", label: "Midbrain", depth: 1 },
  { id: "UBERON:0002028", label: "Hindbrain", depth: 1 },
  { id: "UBERON:0002037", label: "Cerebellum", depth: 2 },
  { id: "UBERON:0000468", label: "Whole animal", depth: 0, exact: true },
];

/** Region filter value for a REGION_GROUPS entry. */
export function regionFilterValue(group: { id: string; exact?: boolean }): string {
  return group.exact ? `exact:${group.id}` : group.id;
}

/**
 * A ?region= URL value for /full-datasets' Region filter: kept if it is the
 * filter value of a REGION_GROUPS entry, else "" (no filter).
 */
export function parseRegionFilterParam(v: unknown): string {
  if (typeof v !== "string") return "";
  return REGION_GROUPS.some((g) => regionFilterValue(g) === v) ? v : "";
}

/** /full-datasets with its Region filter preset to a REGION_GROUPS id. */
export function fullDatasetsRegionHref(groupId: string): string | null {
  const g = REGION_GROUPS.find((x) => x.id === groupId);
  return g ? `/full-datasets?region=${encodeURIComponent(regionFilterValue(g))}` : null;
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
