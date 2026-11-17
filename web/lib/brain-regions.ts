// Brain-region navigator (/regions): the regions of each brain view, the
// hand-curated Brodmann → lobe map, how every tagged dataset is mapped onto a
// view, the source toggle, and the study-kind labels. Pure functions, no
// server imports — the page imports this module client-side, and
// lib/__tests__/brain-regions.test.ts checks it against the vendored UBERON
// list and the dataset configs.
//
// The model: there is one brain per *view* (human = default, mouse =
// optional), not one per species. Every dataset with an anatomy tag is
// mapped onto the view through its UBERON terms, which are cross-species: a
// mouse "cerebral cortex" dataset lands on the human cerebral cortex, and a
// cortical organoid's intended identity likewise. A dataset whose tags name
// a drawn region (a lobe; a mouse structure) is placed on that region. One
// tagged only at a coarser level (e.g. "cerebral cortex", no lobe) is *not*
// spread over the finer regions: it goes into a coarse bucket ("Cerebral
// cortex, no lobe given", "Whole brain", ...) that the page shows next to the
// drawing, and the regions the bucket spans list it as "broader". Tags with
// no brain term at all (whole organism) go into "Not region-specific".
//
// This is the region → UBERON map, kept apart from the geometry: the drawings
// (vendored SVGs in web/public/regions/, registered in lib/region-drawings.ts)
// only mark shapes with data-region="<key>"; everything about what a shape
// means — its UBERON id, which tagged terms count for it (`match`, `exact`) —
// lives here. Swapping in atlas geometry means mapping its structures to
// these keys.

import type { AnatomyTerm } from "@/lib/dataset-tags";
import { COVERAGE_BINS, IN_VITRO } from "@/lib/palette";

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
// (the test fails until you do). (All of them are under "cerebral cortex" in
// UBERON already, so the mouse cortex and the coarse buckets need no help.)
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

// ── Views and regions ───────────────────────────────────────────────────

/** A brain drawing the datasets are mapped onto. Human is the default. */
export type BrainView = "human" | "mouse";

export const BRAIN_VIEWS: readonly BrainView[] = ["human", "mouse"];

export const BRAIN_VIEW_LABELS: Record<BrainView, string> = {
  human: "Human brain",
  mouse: "Mouse brain",
};

/**
 * drawn  — a shape in the view's drawing(s);
 * coarse — a bucket next to the drawing for datasets tagged above the drawn
 *          level (e.g. "cerebral cortex" on the lobe drawing): listed, not
 *          painted onto every region it spans;
 * none   — "Not region-specific": no brain term at all (whole organism,
 *          non-brain tissue / cell line). Catch-all, always last.
 */
export type RegionKind = "drawn" | "coarse" | "none";

export type RegionDef = {
  /** Shape key in the drawings, and the ?region= value. */
  key: string;
  label: string;
  kind: RegionKind;
  /** The region's own UBERON term (shown, linked to OLS). */
  uberon: string;
  /**
   * Grouping terms: a dataset whose closure hits any of these (closureHits,
   * so CURATED_PART_OF applies) is placed here.
   */
  match: readonly string[];
  /**
   * Terms that count only when tagged verbatim — for broad terms whose
   * closure would sweep in too much.
   */
  exact?: readonly string[];
  /**
   * Coarse buckets: the drawn regions the bucket spans. They list its
   * datasets as "broader", and hovering the bucket outlines them.
   */
  covers?: readonly string[];
  /**
   * Drawn regions: other drawn regions this one lies inside (mouse
   * hippocampus in the cortex); their datasets are "broader" here.
   */
  inside?: readonly string[];
  /**
   * REGION_GROUPS id (lib/dataset-tags.ts) for the /full-datasets?region=
   * link; absent = no link (the "not region-specific" bucket).
   */
  filterGroup?: string;
  /** One-line note in the region panel (what the shape / bucket stands for). */
  note?: string;
};

const BRAIN = "UBERON:0000955";
const FOREBRAIN = "UBERON:0001890";
const CEREBRAL_CORTEX = "UBERON:0000956";
const CEREBRAL_HEMISPHERE = "UBERON:0001869";
const HINDBRAIN = "UBERON:0002028";
const WHOLE_ORGANISM = "UBERON:0000468";

const HUMAN_LOBES = ["frontal", "parietal", "temporal", "occipital", "cingulate", "insula"];

const NOT_REGION_SPECIFIC: RegionDef = {
  key: "none",
  label: "Not region-specific",
  kind: "none",
  uberon: WHOLE_ORGANISM,
  match: [],
  note:
    "Anatomy without any brain term: whole-animal readouts (e.g. zebrafish larval behaviour) and any non-brain tissue. These can't be placed on a brain region.",
};

const HUMAN_REGIONS: RegionDef[] = [
  {
    key: "frontal",
    label: "Frontal lobe",
    kind: "drawn",
    uberon: "UBERON:0001870",
    match: ["UBERON:0001870", "UBERON:0016525"],
    filterGroup: "UBERON:0001870",
    note: "Frontal cortex incl. prefrontal (BA9), motor / premotor (BA4, BA6) and Broca's area (BA44, BA45).",
  },
  {
    key: "parietal",
    label: "Parietal lobe",
    kind: "drawn",
    uberon: "UBERON:0001872",
    match: ["UBERON:0001872"],
    filterGroup: "UBERON:0001872",
    note: "Incl. somatosensory cortex (BA1–3), superior parietal (BA5, BA7), angular and supramarginal gyri (BA39, BA40).",
  },
  {
    key: "temporal",
    label: "Temporal lobe",
    kind: "drawn",
    uberon: "UBERON:0016538",
    match: ["UBERON:0016538", "UBERON:0001871"],
    filterGroup: "UBERON:0016538",
    note: "Incl. auditory cortex (BA41, BA42), superior / inferior temporal gyri (BA22, BA20), fusiform (BA37) and temporal pole (BA38).",
  },
  {
    key: "occipital",
    label: "Occipital lobe",
    kind: "drawn",
    uberon: "UBERON:0002021",
    match: ["UBERON:0002021"],
    filterGroup: "UBERON:0002021",
    note: "Incl. primary visual cortex (BA17), mostly on the medial surface.",
  },
  {
    key: "cingulate",
    label: "Cingulate cortex",
    kind: "drawn",
    uberon: "UBERON:0003027",
    match: ["UBERON:0003027"],
    filterGroup: "UBERON:0003027",
    note: "Medial surface; incl. anterior cingulate cortex (BA24).",
  },
  {
    key: "insula",
    label: "Insula",
    kind: "drawn",
    uberon: "UBERON:0002022",
    match: ["UBERON:0002022"],
    filterGroup: "UBERON:0002022",
  },
  // The human drawings (ggsegDKT) show the cortex only. Everything tagged
  // above the lobe level goes in a bucket, narrowest first.
  {
    key: "cortex",
    label: "Cerebral cortex, no lobe given",
    kind: "coarse",
    uberon: CEREBRAL_CORTEX,
    match: [CEREBRAL_CORTEX],
    exact: [CEREBRAL_HEMISPHERE],
    covers: HUMAN_LOBES,
    filterGroup: CEREBRAL_CORTEX,
    note:
      "Tagged “cerebral cortex” without a lobe, e.g. mouse cortex, cortical organoids, fetal cortical cultures. They cover the whole cortex, so they are not counted in any lobe.",
  },
  {
    key: "forebrain",
    label: "Forebrain, no lobe given",
    kind: "coarse",
    uberon: FOREBRAIN,
    match: [FOREBRAIN],
    covers: HUMAN_LOBES,
    filterGroup: FOREBRAIN,
    note:
      "Tagged forebrain or telencephalon (e.g. forebrain-patterned neurons, telencephalic organoids), or a subcortical forebrain structure this cortical drawing does not show.",
  },
  {
    key: "brain",
    label: "Whole brain / no region given",
    kind: "coarse",
    uberon: BRAIN,
    match: [BRAIN],
    covers: HUMAN_LOBES,
    filterGroup: BRAIN,
    note:
      "Tagged “brain”: whole-brain samples (mouse, zebrafish) and neural cells without a regional identity (e.g. NGN2 iNeurons), or a brain structure outside the forebrain that this drawing does not show.",
  },
  NOT_REGION_SPECIFIC,
];

const MOUSE_DRAWN = [
  "olfactory_bulb",
  "cortex",
  "hippocampus",
  "striatum",
  "thalamus",
  "hypothalamus",
  "midbrain",
  "cerebellum",
  "hindbrain",
];
const MOUSE_FOREBRAIN = MOUSE_DRAWN.slice(0, 6);

const MOUSE_REGIONS: RegionDef[] = [
  {
    key: "olfactory_bulb",
    label: "Olfactory bulb",
    kind: "drawn",
    uberon: "UBERON:0002264",
    match: ["UBERON:0002264"],
    filterGroup: "UBERON:0002264",
  },
  {
    key: "cortex",
    label: "Cerebral cortex",
    kind: "drawn",
    uberon: CEREBRAL_CORTEX,
    match: [CEREBRAL_CORTEX],
    filterGroup: CEREBRAL_CORTEX,
    note:
      "The mouse drawing has no lobes: human datasets from any cortical lobe or Brodmann area count here. UBERON files the hippocampal formation under the cerebral cortex, so hippocampus datasets count here too.",
  },
  {
    key: "hippocampus",
    label: "Hippocampal formation",
    kind: "drawn",
    uberon: "UBERON:0002421",
    match: ["UBERON:0002421"],
    inside: ["cortex"],
    filterGroup: "UBERON:0002421",
  },
  {
    key: "striatum",
    label: "Striatum",
    kind: "drawn",
    uberon: "UBERON:0002435",
    match: ["UBERON:0002435"],
    filterGroup: "UBERON:0002435",
  },
  {
    key: "thalamus",
    label: "Thalamus",
    kind: "drawn",
    uberon: "UBERON:0001897",
    match: ["UBERON:0001897"],
    filterGroup: "UBERON:0001897",
  },
  {
    key: "hypothalamus",
    label: "Hypothalamus",
    kind: "drawn",
    uberon: "UBERON:0001898",
    match: ["UBERON:0001898"],
    filterGroup: "UBERON:0001898",
  },
  {
    key: "midbrain",
    label: "Midbrain",
    kind: "drawn",
    uberon: "UBERON:0001891",
    match: ["UBERON:0001891"],
    filterGroup: "UBERON:0001891",
  },
  {
    key: "cerebellum",
    label: "Cerebellum",
    kind: "drawn",
    uberon: "UBERON:0002037",
    match: ["UBERON:0002037"],
    filterGroup: "UBERON:0002037",
  },
  {
    key: "hindbrain",
    label: "Pons and medulla",
    kind: "drawn",
    uberon: HINDBRAIN,
    // Not closureHits(hindbrain): UBERON puts the cerebellum in the hindbrain,
    // and the cerebellum is drawn separately.
    match: ["UBERON:0000988", "UBERON:0001896"],
    exact: [HINDBRAIN, "UBERON:0002298"],
    filterGroup: HINDBRAIN,
  },
  {
    key: "forebrain",
    label: "Forebrain, no subregion given",
    kind: "coarse",
    uberon: FOREBRAIN,
    match: [FOREBRAIN],
    covers: MOUSE_FOREBRAIN,
    filterGroup: FOREBRAIN,
    note:
      "Tagged forebrain, telencephalon or cerebral hemisphere without a finer structure (e.g. forebrain-patterned neurons, telencephalic organoids).",
  },
  {
    key: "brain",
    label: "Whole brain / no region given",
    kind: "coarse",
    uberon: BRAIN,
    match: [BRAIN],
    covers: MOUSE_DRAWN,
    filterGroup: BRAIN,
    note:
      "Tagged “brain”: whole-brain samples (mouse, zebrafish) and neural cells without a regional identity (e.g. NGN2 iNeurons).",
  },
  NOT_REGION_SPECIFIC,
];

export const REGIONS: Readonly<Record<BrainView, readonly RegionDef[]>> = {
  human: HUMAN_REGIONS,
  mouse: MOUSE_REGIONS,
};

export function findRegion(view: BrainView, key: string): RegionDef | undefined {
  return REGIONS[view].find((r) => r.key === key);
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

/** Model systems that are actual tissue. */
export const TISSUE_MODEL_SYSTEMS = ["postmortem", "in_vivo"] as const;
/** Model systems that are in vitro (their anatomy is an intended identity). */
export const IN_VITRO_MODEL_SYSTEMS = [
  "organoid",
  "primary_culture",
  "ineurons",
  "ipsc_other",
  "cell_line",
] as const;

/**
 * The species a dataset's samples come from: the table's organism_key when
 * set (a zebrafish screen can key its genes by human symbol), else the gene
 * species.
 */
export function datasetSpecies(d: RegionDataset): string {
  const keys = d.organism_key ?? [];
  return keys.length > 0 ? keys[0] : d.gene_species;
}

// ── Source toggle ───────────────────────────────────────────────────────

export type SourceKey = "human_tissue" | "mouse_in_vivo" | "zebrafish_in_vivo" | "in_vitro";

export const SOURCES: ReadonlyArray<{ key: SourceKey; label: string; description: string }> = [
  {
    key: "human_tissue",
    label: "Human tissue",
    description: "Human postmortem brain tissue",
  },
  {
    key: "mouse_in_vivo",
    label: "Mouse in vivo",
    description: "Tissue from living mice",
  },
  {
    key: "zebrafish_in_vivo",
    label: "Zebrafish in vivo",
    description: "Zebrafish larvae: whole brain or whole animal",
  },
  {
    key: "in_vitro",
    label: "In vitro",
    description:
      "iPSC-derived neurons and astrocytes, organoids, primary cultures and cell lines, placed by the identity they were patterned towards (not tissue they came from)",
  },
];

export const ALL_SOURCES: readonly SourceKey[] = SOURCES.map((s) => s.key);

/**
 * Which source chip a dataset belongs to; null = not on the page (no anatomy
 * tag, e.g. curated resources, or a model system / species outside the four
 * sources).
 */
export function datasetSource(d: RegionDataset): SourceKey | null {
  if ((d.anatomy ?? []).length === 0) return null;
  const ms = d.model_system ?? "";
  if ((IN_VITRO_MODEL_SYSTEMS as readonly string[]).includes(ms)) return "in_vitro";
  if (!(TISSUE_MODEL_SYSTEMS as readonly string[]).includes(ms)) return null;
  switch (datasetSpecies(d)) {
    case "human":
      return "human_tissue";
    case "mouse":
      return "mouse_in_vivo";
    case "zebrafish":
      return "zebrafish_in_vivo";
    default:
      return null;
  }
}

export function isInVitro(d: RegionDataset): boolean {
  return datasetSource(d) === "in_vitro";
}

/** ?sources=a,b → the selected sources; absent or nothing valid = all. */
export function parseSources(v: unknown): ReadonlySet<SourceKey> {
  if (typeof v !== "string" || v === "") return new Set(ALL_SOURCES);
  const picked = v
    .split(",")
    .filter((s): s is SourceKey => (ALL_SOURCES as readonly string[]).includes(s));
  return new Set(picked.length > 0 ? picked : ALL_SOURCES);
}

/** The ?sources= value for a selection; null when all are selected. */
export function sourcesParam(sel: ReadonlySet<SourceKey>): string | null {
  if (ALL_SOURCES.every((s) => sel.has(s))) return null;
  return ALL_SOURCES.filter((s) => sel.has(s)).join(",");
}

/** Datasets on the page whose source is selected. */
export function filterBySources<D extends RegionDataset>(
  datasets: readonly D[],
  sel: ReadonlySet<SourceKey>,
): D[] {
  return datasets.filter((d) => {
    const s = datasetSource(d);
    return s !== null && sel.has(s);
  });
}

// ── Mapping a dataset onto a view ───────────────────────────────────────

/** Tagged with the region's terms (or a subregion / curated member). */
export function isSpecific(d: RegionDataset, r: RegionDef): boolean {
  if (r.exact && (d.anatomy ?? []).some((t) => r.exact!.includes(t.id))) return true;
  return r.match.some((id) => closureHits(d.anatomy_closure, id));
}

/**
 * Where a dataset goes on a view: the drawn regions it names, else the
 * narrowest coarse bucket that holds it, else "not region-specific" (`none`).
 * Returns region keys: one or more drawn keys, or exactly one other key.
 */
export function placeOnView(d: RegionDataset, view: BrainView): string[] {
  const regions = REGIONS[view];
  const drawn = regions.filter((r) => r.kind === "drawn" && isSpecific(d, r)).map((r) => r.key);
  if (drawn.length > 0) return drawn;
  const coarse = regions.find((r) => r.kind === "coarse" && isSpecific(d, r));
  return [coarse ? coarse.key : "none"];
}

export type RegionTally<D> = {
  /** Placed here. */
  specific: D[];
  /** Drawn regions: from a coarse bucket / enclosing region that spans this one. */
  broader: D[];
};

/**
 * Per-region dataset lists for a view, over the datasets passed in (the
 * caller applies the source toggle and, in the gene view, the gene filter).
 * Every region of the view gets an entry; empty ones are drawn grey.
 */
export function regionTallies<D extends RegionDataset>(
  datasets: readonly D[],
  view: BrainView,
): Map<string, RegionTally<D>> {
  const out = new Map<string, RegionTally<D>>();
  for (const r of REGIONS[view]) out.set(r.key, { specific: [], broader: [] });
  for (const d of datasets) {
    for (const k of placeOnView(d, view)) out.get(k)!.specific.push(d);
  }
  for (const r of REGIONS[view]) {
    if (r.kind !== "drawn") continue;
    const t = out.get(r.key)!;
    const seen = new Set(t.specific.map((d) => d.table_name));
    const add = (ds: readonly D[]) => {
      for (const d of ds) {
        if (seen.has(d.table_name)) continue;
        seen.add(d.table_name);
        t.broader.push(d);
      }
    };
    for (const k of r.inside ?? []) add(out.get(k)!.specific);
    for (const c of REGIONS[view]) {
      if (c.kind === "coarse" && (c.covers ?? []).includes(r.key)) add(out.get(c.key)!.specific);
    }
  }
  return out;
}

/** Tissue vs in-vitro split of a dataset list (for the colour and the ring). */
export function splitInVitro<D extends RegionDataset>(
  ds: readonly D[],
): { tissue: D[]; inVitro: D[] } {
  const tissue: D[] = [];
  const inVitro: D[] = [];
  for (const d of ds) (isInVitro(d) ? inVitro : tissue).push(d);
  return { tissue, inVitro };
}

// ── Study kind ──────────────────────────────────────────────────────────

export type StudyKind =
  | "perturbation"
  | "case_control"
  | "cell_type_reference"
  | "age_association"
  | "observational"
  | "other";

export const STUDY_KIND_LABELS: Record<StudyKind, string> = {
  perturbation: "Perturbation",
  case_control: "Case vs control",
  cell_type_reference: "Cell-type reference",
  age_association: "Age association",
  observational: "Observational",
  other: "Other",
};

export const STUDY_KIND_DESCRIPTIONS: Record<StudyKind, string> = {
  perturbation: "Genes were experimentally perturbed (knockout, CRISPRi/a, knockdown, ...)",
  case_control:
    "Cases (e.g. autism, schizophrenia; postmortem tissue or patient-derived lines) compared with controls; no gene was perturbed",
  cell_type_reference:
    "Marker genes of cell types (each cluster vs all other clusters); not a disease comparison",
  age_association:
    "Genes whose expression changes with donor age (observational); not a disease comparison",
  observational:
    "No manipulation and no case/control comparison (e.g. regulatory networks inferred from unperturbed cells)",
  other: "Experiment type not tagged",
};

/**
 * Per-table study kinds where the rule in studyKind() gets it wrong, each
 * checked against the dataset config. The rule labels all postmortem tissue
 * "case vs control"; these postmortem tables are not disease comparisons.
 * (The genuine case-control postmortem tables, psychscreen asd / bipolar /
 * schizophrenia, gandal-2018, both gandal-2022 tables and velmeshev_2019,
 * are left to the rule.)
 */
export const STUDY_KIND_OVERRIDES: Readonly<Record<string, StudyKind>> = {
  // wamsley-postmortem-autism: per-cluster marker genes, each cell-type
  // cluster vs all other clusters; a cell-type reference, not ASD vs control.
  wamsley_2024_cluster_markers: "cell_type_reference",
  // psychscreen: differential expression with donor age, not a diagnosis.
  psychscreen_age_deg: "age_association",
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
 * STUDY_KIND_OVERRIDES first; then a perturbation experiment_type is a
 * perturbation, postmortem tissue and patient-derived lines are case vs
 * control (no gene manipulated), and other observational studies are
 * observational.
 */
export function studyKind(d: RegionDataset): StudyKind {
  const o = STUDY_KIND_OVERRIDES[d.table_name];
  if (o) return o;
  const et = d.experiment_type ?? "";
  if (PERTURBATION_TYPES.has(et)) return "perturbation";
  if (d.model_system === "postmortem" || et === "patient_lines") return "case_control";
  if (et === "observational") return "observational";
  return "other";
}

// ── Gene view (/regions?perturbed=X&target=Y) ───────────────────────────

/**
 * Tables whose "perturbed" gene column is not a perturbation. The gene view
 * does not count a gene in that column as perturbed: /api/gene-regions
 * leaves the table out of the perturbed matches and lists it under
 * `excluded`, so the page can say why.
 */
export const NOT_PERTURBED_TABLES: Readonly<Record<string, string>> = {
  // fleck-organoid-grn: the "tf" column holds Pando-inferred regulators from
  // multi-omic profiling of *unperturbed* organoids. The config's
  // `assay: perturbation` and `perturbed_or_target: perturbed` are a
  // mislabel: the TF is a regulator in an inferred network, nothing was
  // knocked out.
  fleck_2023_organoid_grn:
    "an inferred transcription-factor regulator in a gene-regulatory network from unperturbed organoids (Fleck 2023), not a perturbation",
};

/** The gene view keeps only the tables the gene query matched. */
export function datasetsWithGene<D extends RegionDataset>(
  datasets: readonly D[],
  tables: { has: (table: string) => boolean },
): D[] {
  return datasets.filter((d) => tables.has(d.table_name));
}

// ── Links ───────────────────────────────────────────────────────────────

/** /matrix restricted to some source tables (By study view). */
export function matrixTablesHref(tables: readonly string[]): string {
  return `/matrix?tables=${tables.map(encodeURIComponent).join(",")}`;
}

// ── Colour scale ────────────────────────────────────────────────────────

/** Fill for a region with `n` tissue datasets (single-hue sequential). */
export const COUNT_BINS = COVERAGE_BINS;

/** Fill for a region that has in-vitro datasets only (plus the dashed ring). */
export const IN_VITRO_ONLY_FILL = IN_VITRO.fillOnly;
/** Dashed ring / border colour that marks in-vitro data. */
export const IN_VITRO_STROKE = IN_VITRO.stroke;

export function countFill(n: number): string {
  let fill = COUNT_BINS[0].fill;
  for (const b of COUNT_BINS) if (n >= b.min) fill = b.fill;
  return fill;
}

/** Text colour that reads on countFill(n). */
export function countInk(n: number): string {
  let ink = COUNT_BINS[0].ink;
  for (const b of COUNT_BINS) if (n >= b.min) ink = b.ink;
  return ink;
}

/**
 * Fill for a region from its tissue / in-vitro counts: the count ramp over
 * tissue datasets only; in-vitro-only regions get a pale violet (and the
 * page adds the dashed in-vitro ring), so organoids never read as tissue.
 */
export function regionFill(tissue: number, inVitro: number): string {
  if (tissue === 0 && inVitro > 0) return IN_VITRO_ONLY_FILL;
  return countFill(tissue);
}

export function olsUrl(uberon: string): string {
  return `https://www.ebi.ac.uk/ols4/ontologies/uberon/classes?obo_id=${encodeURIComponent(uberon)}`;
}
