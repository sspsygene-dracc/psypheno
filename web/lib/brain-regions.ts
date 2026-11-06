// Brain-region navigator (/regions): the drawn regions, the hand-curated
// Brodmann → lobe map, and the rules that decide which datasets a region
// "has". Pure functions, no server imports — the page imports this module
// client-side, and lib/__tests__/brain-regions.test.ts checks it against the
// vendored UBERON list and the dataset configs.
//
// This is the region → UBERON map, kept apart from the geometry: the drawings
// (vendored SVGs in web/public/regions/, registered in lib/region-drawings.ts)
// only mark shapes with data-region="<key>"; everything about what a shape
// means — its UBERON id, which tagged terms count for it (`match`, `exact`,
// i.e. "also counts as"), which broader terms contain it (`within`) — lives
// here. Swapping in atlas geometry means mapping its structures to these keys.

import type { AnatomyTerm } from "@/lib/dataset-tags";

// ── Hand-curated part-of links ──────────────────────────────────────────
//
// Why this exists: a region matches a dataset through `anatomy_closure` (the
// tagged UBERON terms plus all their is_a / part_of ancestors). UBERON's
// Brodmann-area → lobe links are incomplete, so the closure alone gets lobes
// wrong. In the vendored release (data/ontology/uberon_terms.tsv,
// uberon-basic 2026-10-01):
//   - BA6 and BA44 are not under frontal cortex (BA4, BA9, BA45 are);
//   - BA20, BA22, BA37, BA38, BA41, BA42 are not under temporal cortex;
//   - BA1, BA2, BA3, BA5, BA7, BA39 are not under parietal lobe (BA40 is).
// A dataset tagged "temporal cortex" (gandal-2018) and one tagged with the
// temporal Brodmann areas (gandal-2022) should light up the same lobe, so we
// assign every Brodmann area we tag to its lobe here, by hand. Entries UBERON
// already has are listed too, so this table is the full assignment and reads
// on its own. Add a row when a dataset starts tagging a new Brodmann area
// (the test fails until you do).
//
// Keys are the grouping terms (the same ids /full-datasets' Region filter
// uses); values are tagged terms that count as part of them.
export const CURATED_PART_OF: Readonly<Record<string, readonly string[]>> = {
  // frontal cortex
  "UBERON:0001870": [
    "UBERON:0013535", // BA4 (primary motor)            — in UBERON
    "UBERON:0006472", // BA6 (premotor / SMA)           — missing in UBERON
    "UBERON:0013540", // BA9 (dorsolateral prefrontal)  — in UBERON
    "UBERON:0006481", // BA44 (pars opercularis)        — missing in UBERON
    "UBERON:0006482", // BA45 (pars triangularis)       — in UBERON
  ],
  // temporal cortex
  "UBERON:0016538": [
    "UBERON:0013551", // BA20 (inferior temporal gyrus)
    "UBERON:0013553", // BA22 (superior temporal gyrus)
    "UBERON:0006478", // BA37 (occipitotemporal / fusiform)
    "UBERON:0006479", // BA38 (temporal pole)
    "UBERON:0006095", // BA41 (anterior transverse temporal)
    "UBERON:0006096", // BA42 (posterior transverse temporal)
  ],
  // parietal lobe
  "UBERON:0001872": [
    "UBERON:0006099", // BA1 (primary somatosensory)
    "UBERON:0013533", // BA2 (primary somatosensory)
    "UBERON:0006100", // BA3 (primary somatosensory)
    "UBERON:0006471", // BA5 (superior parietal)
    "UBERON:0013538", // BA7 (superior parietal / precuneus)
    "UBERON:0006480", // BA39 (angular gyrus)
    "UBERON:0013573", // BA40 (supramarginal gyrus)    — in UBERON
  ],
  // occipital lobe
  "UBERON:0002021": [
    "UBERON:8440010", // BA17 (primary visual)          — in UBERON
  ],
  // cingulate cortex
  "UBERON:0003027": [
    "UBERON:0006101", // BA24 (anterior cingulate)      — in UBERON
  ],
};

/**
 * True when a dataset tagged with `closure` falls under grouping term
 * `regionId`: the closure contains it, or contains a term CURATED_PART_OF
 * files under it.
 */
export function closureHits(
  closure: readonly string[] | undefined,
  regionId: string,
): boolean {
  if (!closure) return false;
  if (closure.includes(regionId)) return true;
  const extra = CURATED_PART_OF[regionId];
  return !!extra && extra.some((id) => closure.includes(id));
}

// ── Drawn regions ───────────────────────────────────────────────────────

export type RegionSpecies = "human" | "mouse" | "zebrafish";

export const REGION_SPECIES: readonly RegionSpecies[] = ["human", "mouse", "zebrafish"];

export type RegionDef = {
  /** Shape key in the drawings, and the ?region= value. */
  key: string;
  label: string;
  /** The region's own UBERON term (shown, linked to OLS). */
  uberon: string;
  /**
   * Grouping terms: a dataset whose closure hits any of these (closureHits,
   * so CURATED_PART_OF applies) is specific to this region.
   */
  match: readonly string[];
  /**
   * Terms that count only when tagged verbatim — for broad terms whose
   * closure would sweep in everything (e.g. "multicellular organism" is an
   * ancestor of every brain term).
   */
  exact?: readonly string[];
  /**
   * Broader terms this region lies within. A dataset tagged with one of these
   * (and not specific to the region) is listed as "broader" — e.g. a
   * whole-brain dataset under every mouse region — instead of colouring it.
   * Also drives the in-vitro tray's "intended identity" outline.
   */
  within: readonly string[];
  /** One-line note in the region panel (what the shape stands for). */
  note?: string;
  /**
   * Not a coloured shape: the brain outline, for datasets tagged only with a
   * broad term ("brain", "cerebral cortex"). Rendered as a button under the
   * drawing so those datasets stay reachable without painting every region.
   */
  pseudo?: boolean;
};

const BRAIN = "UBERON:0000955";
const FOREBRAIN = "UBERON:0001890";
const TELENCEPHALON = "UBERON:0001893";
const CEREBRAL_CORTEX = "UBERON:0000956";
const CEREBRAL_HEMISPHERE = "UBERON:0001869";
const DIENCEPHALON = "UBERON:0001894";
const HINDBRAIN = "UBERON:0002028";
const WHOLE_ORGANISM = "UBERON:0000468";

const CORTEX_WITHIN = [CEREBRAL_CORTEX, CEREBRAL_HEMISPHERE, TELENCEPHALON, FOREBRAIN, BRAIN];

const HUMAN_REGIONS: RegionDef[] = [
  {
    key: "frontal",
    label: "Frontal lobe",
    uberon: "UBERON:0001870",
    match: ["UBERON:0001870", "UBERON:0016525"],
    within: CORTEX_WITHIN,
    note: "Frontal cortex incl. prefrontal (BA9), motor / premotor (BA4, BA6) and Broca's area (BA44, BA45).",
  },
  {
    key: "parietal",
    label: "Parietal lobe",
    uberon: "UBERON:0001872",
    match: ["UBERON:0001872"],
    within: CORTEX_WITHIN,
    note: "Incl. somatosensory cortex (BA1–3), superior parietal (BA5, BA7), angular and supramarginal gyri (BA39, BA40).",
  },
  {
    key: "temporal",
    label: "Temporal lobe",
    uberon: "UBERON:0016538",
    match: ["UBERON:0016538", "UBERON:0001871"],
    within: CORTEX_WITHIN,
    note: "Incl. auditory cortex (BA41, BA42), superior / inferior temporal gyri (BA22, BA20), fusiform (BA37) and temporal pole (BA38).",
  },
  {
    key: "occipital",
    label: "Occipital lobe",
    uberon: "UBERON:0002021",
    match: ["UBERON:0002021"],
    within: CORTEX_WITHIN,
    note: "Incl. primary visual cortex (BA17), mostly on the medial surface.",
  },
  {
    key: "cingulate",
    label: "Cingulate cortex",
    uberon: "UBERON:0003027",
    match: ["UBERON:0003027"],
    within: CORTEX_WITHIN,
    note: "Medial surface; incl. anterior cingulate cortex (BA24).",
  },
  {
    key: "insula",
    label: "Insula",
    uberon: "UBERON:0002022",
    match: ["UBERON:0002022"],
    within: CORTEX_WITHIN,
  },
  // The human drawings (ggsegDKT) show the cortex only: a dataset tagged with
  // a subcortical structure would be listed under "not placed on this drawing".
  {
    key: "whole",
    label: "Whole brain / cortex (unspecified)",
    uberon: BRAIN,
    match: [],
    exact: [BRAIN, CEREBRAL_CORTEX, CEREBRAL_HEMISPHERE, TELENCEPHALON, FOREBRAIN],
    within: [],
    pseudo: true,
    note: "Datasets tagged only with a broad term (brain, cerebral cortex, ...), not a specific lobe.",
  },
];

const MOUSE_REGIONS: RegionDef[] = [
  {
    key: "olfactory_bulb",
    label: "Olfactory bulb",
    uberon: "UBERON:0002264",
    match: ["UBERON:0002264"],
    within: [TELENCEPHALON, FOREBRAIN, BRAIN],
  },
  {
    key: "cortex",
    label: "Cerebral cortex",
    uberon: CEREBRAL_CORTEX,
    match: [CEREBRAL_CORTEX],
    within: [CEREBRAL_HEMISPHERE, TELENCEPHALON, FOREBRAIN, BRAIN],
    note: "UBERON files the hippocampal formation under cerebral cortex, so hippocampus datasets count here too.",
  },
  {
    key: "hippocampus",
    label: "Hippocampal formation",
    uberon: "UBERON:0002421",
    match: ["UBERON:0002421"],
    within: CORTEX_WITHIN,
  },
  {
    key: "striatum",
    label: "Striatum",
    uberon: "UBERON:0002435",
    match: ["UBERON:0002435"],
    within: [TELENCEPHALON, FOREBRAIN, BRAIN],
  },
  {
    key: "thalamus",
    label: "Thalamus",
    uberon: "UBERON:0001897",
    match: ["UBERON:0001897"],
    within: [DIENCEPHALON, FOREBRAIN, BRAIN],
  },
  {
    key: "hypothalamus",
    label: "Hypothalamus",
    uberon: "UBERON:0001898",
    match: ["UBERON:0001898"],
    within: [DIENCEPHALON, FOREBRAIN, BRAIN],
  },
  {
    key: "midbrain",
    label: "Midbrain",
    uberon: "UBERON:0001891",
    match: ["UBERON:0001891"],
    within: [BRAIN],
  },
  {
    key: "cerebellum",
    label: "Cerebellum",
    uberon: "UBERON:0002037",
    match: ["UBERON:0002037"],
    within: [HINDBRAIN, BRAIN],
  },
  {
    key: "hindbrain",
    label: "Pons and medulla",
    uberon: HINDBRAIN,
    // Not closureHits(hindbrain): UBERON puts the cerebellum in the hindbrain,
    // and the cerebellum is drawn separately.
    match: ["UBERON:0000988", "UBERON:0001896"],
    exact: [HINDBRAIN, "UBERON:0002298"],
    within: [BRAIN],
  },
  {
    key: "whole",
    label: "Whole brain (unspecified)",
    uberon: BRAIN,
    match: [],
    exact: [BRAIN, FOREBRAIN, TELENCEPHALON, CEREBRAL_HEMISPHERE],
    within: [],
    pseudo: true,
    note: "Datasets tagged only with a broad term (whole brain, forebrain, ...).",
  },
];

const ZEBRAFISH_REGIONS: RegionDef[] = [
  {
    key: "larva",
    label: "Whole larva",
    uberon: WHOLE_ORGANISM,
    // Every brain term has "multicellular organism" as an ancestor, so only a
    // verbatim whole-organism tag (behaviour screens) counts here.
    match: [],
    exact: [WHOLE_ORGANISM],
    within: [],
    note: "Whole-animal readouts, e.g. larval behaviour.",
  },
  {
    key: "brain",
    label: "Brain",
    uberon: BRAIN,
    match: [BRAIN],
    within: [WHOLE_ORGANISM],
  },
];

export const REGIONS: Readonly<Record<RegionSpecies, readonly RegionDef[]>> = {
  human: HUMAN_REGIONS,
  mouse: MOUSE_REGIONS,
  zebrafish: ZEBRAFISH_REGIONS,
};

export function findRegion(species: RegionSpecies, key: string): RegionDef | undefined {
  return REGIONS[species].find((r) => r.key === key);
}

// ── Datasets ────────────────────────────────────────────────────────────

/** The subset of a /api/full-datasets entry this module reads. */
export type RegionDataset = {
  table_name: string;
  gene_species: string;
  organism_key?: string[] | null;
  model_system?: string | null;
  experiment_type?: string | null;
  anatomy?: readonly AnatomyTerm[];
  anatomy_closure?: readonly string[];
};

/** Model systems drawn on the anatomy (actual tissue). */
export const TISSUE_MODEL_SYSTEMS = ["postmortem", "in_vivo"] as const;
/** Model systems shown in the in-vitro tray (intended identity only). */
export const IN_VITRO_MODEL_SYSTEMS = [
  "organoid",
  "primary_culture",
  "ineurons",
  "ipsc_other",
  "cell_line",
] as const;

export type DatasetPlacement = "tissue" | "in_vitro" | "excluded";

/**
 * Where a dataset goes on /regions. Curated resources (no anatomy) and
 * untagged tables are left off the page.
 */
export function placement(d: RegionDataset): DatasetPlacement {
  // Anything without an anatomy tag stays off the page, whatever its model
  // system (curated resources have none by design).
  if ((d.anatomy ?? []).length === 0) return "excluded";
  const ms = d.model_system ?? "";
  if ((TISSUE_MODEL_SYSTEMS as readonly string[]).includes(ms)) return "tissue";
  if ((IN_VITRO_MODEL_SYSTEMS as readonly string[]).includes(ms)) return "in_vitro";
  return "excluded";
}

/**
 * The species a dataset's samples come from: the table's organism_key when
 * set (a zebrafish screen can key its genes by human symbol), else the gene
 * species.
 */
export function datasetSpecies(d: RegionDataset): string {
  const keys = d.organism_key ?? [];
  return keys.length > 0 ? keys[0] : d.gene_species;
}

/** Specific to a region: tagged with it, a subregion, or a curated member. */
export function isSpecific(d: RegionDataset, r: RegionDef): boolean {
  if (r.exact && (d.anatomy ?? []).some((t) => r.exact!.includes(t.id))) return true;
  return r.match.some((id) => closureHits(d.anatomy_closure, id));
}

/** Covers a broader region the drawn one lies within (e.g. whole brain). */
export function isBroader(d: RegionDataset, r: RegionDef): boolean {
  if (isSpecific(d, r)) return false;
  return (d.anatomy ?? []).some((t) => r.within.includes(t.id));
}

export type RegionCounts = {
  specific: RegionDataset[];
  broader: RegionDataset[];
};

/**
 * Per-region dataset lists for one species' tissue datasets. Regions with
 * nothing tagged get empty lists (drawn grey).
 *
 * The gene-first view (/regions?gene=X, not built yet) plugs in by passing
 * only the tables where that gene was perturbed or measured.
 */
export function regionCounts<D extends RegionDataset>(
  datasets: readonly D[],
  species: RegionSpecies,
): Map<string, { specific: D[]; broader: D[] }> {
  const tissue = datasets.filter(
    (d) => placement(d) === "tissue" && datasetSpecies(d) === species,
  );
  const out = new Map<string, { specific: D[]; broader: D[] }>();
  for (const r of REGIONS[species]) {
    out.set(r.key, {
      specific: tissue.filter((d) => isSpecific(d, r)),
      broader: tissue.filter((d) => isBroader(d, r)),
    });
  }
  return out;
}

/** Tissue datasets of a species that no drawn region claims (shown as a note). */
export function unplacedTissue<D extends RegionDataset>(
  datasets: readonly D[],
  species: RegionSpecies,
): D[] {
  return datasets.filter(
    (d) =>
      placement(d) === "tissue" &&
      datasetSpecies(d) === species &&
      !REGIONS[species].some((r) => isSpecific(d, r) || isBroader(d, r)),
  );
}

// ── In-vitro tray ───────────────────────────────────────────────────────

export type TrayGroup = {
  key: string;
  label: string;
  description: string;
  /**
   * The identity term: drawn regions matching or lying within it get the
   * dotted "intended identity" outline. null = no brain region.
   */
  identity: string | null;
};

/** In order; a dataset goes in the first group it fits. */
export const TRAY_GROUPS: readonly TrayGroup[] = [
  {
    key: "cortical",
    label: "Cortical identity",
    description: "Cortical organoids, cortical primary cultures",
    identity: CEREBRAL_CORTEX,
  },
  {
    key: "forebrain",
    label: "Forebrain / telencephalic",
    description: "Forebrain-patterned neurons, telencephalic organoids",
    identity: FOREBRAIN,
  },
  {
    key: "brain",
    label: "Neural, no regional identity",
    description: "Unpatterned organoids, NGN2 iNeurons, iPSC-derived astrocytes / NPCs",
    identity: BRAIN,
  },
  {
    key: "non_neural",
    label: "Non-neural cell lines",
    description: "E.g. HEK293T (kidney)",
    identity: null,
  },
];

export function trayGroupOf(d: RegionDataset): TrayGroup {
  const c = d.anatomy_closure ?? [];
  for (const g of TRAY_GROUPS) {
    if (g.identity && closureHits(c, g.identity)) return g;
  }
  return TRAY_GROUPS[TRAY_GROUPS.length - 1];
}

export function trayGroups<D extends RegionDataset>(
  datasets: readonly D[],
): Map<string, D[]> {
  const out = new Map<string, D[]>(TRAY_GROUPS.map((g) => [g.key, [] as D[]]));
  for (const d of datasets) {
    if (placement(d) !== "in_vitro") continue;
    out.get(trayGroupOf(d).key)!.push(d);
  }
  return out;
}

/**
 * Does a tray group's intended identity cover drawn region `r`? (Used for the
 * dotted outline, and for the "modelled in vitro" list in a region panel.)
 */
export function trayCoversRegion(g: TrayGroup, r: RegionDef): boolean {
  if (!g.identity) return false;
  return r.uberon === g.identity || r.match.includes(g.identity) || r.within.includes(g.identity);
}

// ── Study kind (perturbation vs case-control) ───────────────────────────

export type StudyKind = "perturbation" | "case_control" | "observational" | "other";

export const STUDY_KIND_LABELS: Record<StudyKind, string> = {
  perturbation: "Perturbation",
  case_control: "Case vs control",
  observational: "Observational",
  other: "Other",
};

const PERTURBATION_TYPES = new Set([
  "crispr_ko",
  "crispri",
  "crispra",
  "knockdown",
  "overexpression",
  "isogenic_variant",
  "drug_treatment",
  "multiple",
]);

/**
 * Postmortem tissue and patient-derived lines are case vs control (no gene
 * manipulated); a perturbation experiment_type is a perturbation; the rest
 * observational.
 */
export function studyKind(d: RegionDataset): StudyKind {
  const et = d.experiment_type ?? "";
  if (PERTURBATION_TYPES.has(et)) return "perturbation";
  if (d.model_system === "postmortem" || et === "patient_lines") return "case_control";
  if (et === "observational") return "observational";
  return "other";
}

// ── Colour scale ────────────────────────────────────────────────────────

/** Fill for a region with `n` specific datasets (single-hue sequential). */
export const COUNT_BINS: ReadonlyArray<{ min: number; label: string; fill: string }> = [
  { min: 0, label: "0", fill: "#e1e5ea" },
  { min: 1, label: "1", fill: "#cfe1f3" },
  { min: 2, label: "2", fill: "#93bde4" },
  { min: 3, label: "3–4", fill: "#4f93d0" },
  { min: 5, label: "5+", fill: "#1f5f9e" },
];

export function countFill(n: number): string {
  let fill = COUNT_BINS[0].fill;
  for (const b of COUNT_BINS) if (n >= b.min) fill = b.fill;
  return fill;
}

/** Text colour that reads on countFill(n). */
export function countInk(n: number): string {
  return n >= 3 ? "#ffffff" : "#1f2937";
}

export function olsUrl(uberon: string): string {
  return `https://www.ebi.ac.uk/ols4/ontologies/uberon/classes?obo_id=${encodeURIComponent(uberon)}`;
}
