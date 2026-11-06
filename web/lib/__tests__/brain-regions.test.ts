import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  ALL_SOURCES,
  BRAIN_VIEWS,
  CURATED_PART_OF,
  NOT_PERTURBED_TABLES,
  REGIONS,
  STUDY_KIND_OVERRIDES,
  countFill,
  datasetSource,
  datasetsWithGene,
  filterBySources,
  isSpecific,
  matrixTablesHref,
  parseSources,
  placeOnView,
  regionFill,
  regionTallies,
  sourcesParam,
  splitInVitro,
  studyKind,
  type BrainView,
  type RegionDataset,
} from "@/lib/brain-regions";
import {
  REGION_GROUPS,
  fullDatasetsRegionHref,
  matchesRegionFilter,
  parseRegionFilterParam,
  regionFilterValue,
} from "@/lib/dataset-tags";
import { REGION_DRAWINGS, svgRegionKeys } from "@/lib/region-drawings";
import allenMap from "@/lib/regions/allen-mouse-regions.json";
import dktLobes from "@/lib/regions/dkt-lobes.json";

const svgText = (src: string) => fs.readFileSync(path.resolve(__dirname, "../../public", `.${src}`), "utf8");
const drawingKeys = (src: string) => svgRegionKeys(svgText(src));

// ── The vendored UBERON list (data/ontology/uberon_terms.tsv) ───────────

const REPO = path.resolve(__dirname, "../../..");
const UBERON = new Map<string, { label: string; ancestors: string[] }>();
for (const line of fs
  .readFileSync(path.join(REPO, "data/ontology/uberon_terms.tsv"), "utf8")
  .split("\n")) {
  if (!line || line.startsWith("#") || line.startsWith("id\t")) continue;
  const [id, label, anc] = line.split("\t");
  UBERON.set(id, { label, ancestors: anc ? anc.split(",") : [] });
}

/** A dataset tagged with `ids`, closure computed from the vendored UBERON. */
function ds(ids: string[], extra: Partial<RegionDataset> = {}): RegionDataset {
  const closure = new Set<string>();
  for (const id of ids) {
    closure.add(id);
    for (const a of UBERON.get(id)?.ancestors ?? []) closure.add(a);
  }
  return {
    table_name: extra.table_name ?? ids.join("+"),
    gene_species: "human",
    model_system: "postmortem",
    anatomy: ids.map((id) => ({ id, label: UBERON.get(id)?.label ?? id })),
    anatomy_closure: [...closure],
    ...extra,
  };
}

const CONFIG_DIR = path.join(REPO, "data/datasets");
const configs = fs
  .readdirSync(CONFIG_DIR)
  .map((name) => path.join(CONFIG_DIR, name, "config.yaml"))
  .filter((p) => fs.existsSync(p))
  .map((p) => fs.readFileSync(p, "utf8"));

/** Every UBERON id written in a dataset config (anatomy tags). */
function configAnatomyIds(): string[] {
  const ids = new Set<string>();
  for (const text of configs) {
    for (const m of text.matchAll(/^\s*-\s*(UBERON:\d+)/gm)) ids.add(m[1]);
  }
  return [...ids].sort();
}

/** Table names of the configs whose (top-level) model_system is `ms`. */
function tablesWithModelSystem(ms: string): string[] {
  const out: string[] = [];
  for (const text of configs) {
    if (!new RegExp(`^model_system:\\s*${ms}\\s*$`, "m").test(text)) continue;
    for (const m of text.matchAll(/^\s*-\s*table:\s*(\S+)/gm)) out.push(m[1]);
  }
  return out.sort();
}
const allConfigTables = () => configs.flatMap((t) => Array.from(t.matchAll(/^\s*-\s*table:\s*(\S+)/gm), (m) => m[1]));

const HUMAN_LOBES = ["frontal", "parietal", "temporal", "occipital", "cingulate"];
const region = (view: BrainView, key: string) => REGIONS[view].find((r) => r.key === key)!;

const BRAIN = "UBERON:0000955";
const CORTEX = "UBERON:0000956";
const FOREBRAIN = "UBERON:0001890";
const TELENCEPHALON = "UBERON:0001893";
const WHOLE_ORGANISM = "UBERON:0000468";
const KIDNEY = "UBERON:0002113";
const mouseVivo = { gene_species: "mouse", organism_key: ["mouse"], model_system: "in_vivo" };
const fishVivo = { gene_species: "human", organism_key: ["zebrafish"], model_system: "in_vivo" };

describe("region map", () => {
  it("references only UBERON ids that exist in the vendored list", () => {
    for (const v of BRAIN_VIEWS) {
      for (const r of REGIONS[v]) {
        for (const id of [r.uberon, ...r.match, ...(r.exact ?? [])]) {
          expect(UBERON.has(id), `${v}/${r.key}: ${id}`).toBe(true);
        }
      }
    }
    for (const [k, ids] of Object.entries(CURATED_PART_OF)) {
      expect(UBERON.has(k), k).toBe(true);
      for (const id of ids) expect(UBERON.has(id), `${k} -> ${id}`).toBe(true);
    }
    for (const g of REGION_GROUPS) expect(UBERON.has(g.id), g.label).toBe(true);
  });

  it("gives each view drawn regions, then coarse buckets, then one catch-all", () => {
    for (const v of BRAIN_VIEWS) {
      const kinds = REGIONS[v].map((r) => r.kind);
      expect(kinds[kinds.length - 1], v).toBe("none");
      expect(kinds.filter((k) => k === "none"), v).toHaveLength(1);
      expect(kinds.lastIndexOf("drawn"), v).toBeLessThan(kinds.indexOf("coarse"));
      const keys = new Set(REGIONS[v].map((r) => r.key));
      for (const r of REGIONS[v]) {
        for (const k of [...(r.covers ?? []), ...(r.inside ?? [])]) {
          expect(REGIONS[v].find((x) => x.key === k)?.kind, `${v}/${r.key} -> ${k}`).toBe("drawn");
        }
        if (r.filterGroup) {
          expect(fullDatasetsRegionHref(r.filterGroup), `${v}/${r.key}`).not.toBeNull();
        } else {
          expect(r.kind, `${v}/${r.key} has no /full-datasets link`).toBe("none");
        }
      }
      expect(keys.size).toBe(REGIONS[v].length);
    }
  });

  it("assigns every tagged Brodmann area to exactly one human lobe", () => {
    const brodmann = configAnatomyIds().filter((id) =>
      /Brodmann|transverse temporal area/.test(UBERON.get(id)?.label ?? ""),
    );
    expect(brodmann.length).toBeGreaterThanOrEqual(20);
    for (const id of brodmann) {
      const lobes = HUMAN_LOBES.filter((k) => isSpecific(ds([id]), region("human", k)));
      expect(lobes, `${id} (${UBERON.get(id)?.label})`).toHaveLength(1);
    }
  });

  it("fixes the lobe links UBERON is missing", () => {
    const temporal = region("human", "temporal");
    // BA22 is not under temporal cortex in UBERON …
    expect(UBERON.get("UBERON:0013553")!.ancestors).not.toContain("UBERON:0016538");
    // … but the curated map puts it there.
    expect(isSpecific(ds(["UBERON:0013553"]), temporal)).toBe(true);
    // gandal-2018 (frontal + temporal cortex) and the gandal-2022 Brodmann
    // areas light the same lobes.
    expect(placeOnView(ds(["UBERON:0001870", "UBERON:0016538"]), "human")).toEqual(["frontal", "temporal"]);
  });

  it("applies the curated map to /full-datasets' Region filter too", () => {
    expect(matchesRegionFilter(ds(["UBERON:0006472"]), "UBERON:0001870")).toBe(true); // BA6
    expect(matchesRegionFilter(ds(["UBERON:0006472"]), "UBERON:0016538")).toBe(false);
  });

  it("places every tagged brain term on a region or a brain bucket of both views", () => {
    const noBrain = new Set([WHOLE_ORGANISM, KIDNEY]);
    for (const id of configAnatomyIds()) {
      for (const v of BRAIN_VIEWS) {
        const keys = placeOnView(ds([id]), v);
        const label = `${v}: ${id} (${UBERON.get(id)?.label})`;
        if (noBrain.has(id)) expect(keys, label).toEqual(["none"]);
        else expect(keys, label).not.toContain("none");
      }
    }
  });

  it("vendors drawings that are safe to inline, with the registered viewBox", () => {
    for (const v of BRAIN_VIEWS) {
      for (const d of REGION_DRAWINGS[v]) {
        const text = svgText(d.src);
        expect(text, d.src).toMatch(/^<svg[^>]*viewBox=/);
        expect(text, d.src).not.toMatch(/<script|\son\w+=|href="(?!#)|url\((?!#)/i);
        const vb = /viewBox="0 0 ([\d.]+) ([\d.]+)"/.exec(text)!;
        expect([Number(vb[1]), Number(vb[2])], d.src).toEqual(d.viewBox);
      }
    }
  });

  it("has no zebrafish drawing", () => {
    expect(Object.keys(REGION_DRAWINGS).sort()).toEqual([...BRAIN_VIEWS].sort());
    expect(fs.existsSync(path.resolve(__dirname, "../../public/regions/zebrafish-larva.svg"))).toBe(false);
  });

  it("draws every drawn region, and only known drawn regions", () => {
    for (const v of BRAIN_VIEWS) {
      const drawn = new Set(REGION_DRAWINGS[v].flatMap((d) => drawingKeys(d.src)));
      for (const r of REGIONS[v]) {
        if (r.kind === "drawn") expect(drawn.has(r.key), `${v}/${r.key}`).toBe(true);
      }
      for (const k of drawn) {
        expect(REGIONS[v].find((r) => r.key === k)?.kind, `${v}: shape ${k}`).toBe("drawn");
      }
    }
  });
});

describe("atlas structure maps", () => {
  const svgFile = (name: string) =>
    fs.readFileSync(path.resolve(__dirname, "../../public/regions", name), "utf8");
  /** Attributes of every <path> in an SVG string. */
  const pathAttrs = (svg: string) =>
    Array.from(svg.matchAll(/<path\b([^>]*)>/g), (m) =>
      Object.fromEntries(Array.from(m[1].matchAll(/([\w-]+)="([^"]*)"/g), (a) => [a[1], a[2]])),
    );

  it("maps Allen structures to mouse regions with matching UBERON ids", () => {
    for (const rule of allenMap.rules) {
      if (rule.region === null) continue;
      const r = REGIONS.mouse.find((x) => x.key === rule.region);
      expect(r, rule.region).toBeDefined();
      expect(rule.uberon).toBe(r!.uberon);
    }
    // Every drawn mouse region comes from some rule.
    const ruled = new Set(allenMap.rules.map((r) => r.region));
    for (const r of REGIONS.mouse) if (r.kind === "drawn") expect(ruled.has(r.key), r.key).toBe(true);
  });

  it("tags every Allen polygon in the mouse drawing by the first matching rule", () => {
    const paths = pathAttrs(svgFile("mouse-sagittal.svg")).filter((a) => a["data-allen-id"]);
    expect(paths.length).toBeGreaterThan(100);
    const regionFor = (sid: number, ancestors: number[]): string | null => {
      for (const rule of allenMap.rules) {
        for (const a of rule.allen) {
          if ("exact" in a && a.exact ? sid === a.id : ancestors.includes(a.id)) return rule.region;
        }
      }
      return null;
    };
    for (const a of paths) {
      const ancestors = a["data-allen-path"].split("/").filter(Boolean).map(Number);
      const expected = regionFor(Number(a["data-allen-id"]), ancestors);
      expect(a["data-region"] ?? null, `${a["data-allen-acronym"]} (${a["data-allen-id"]})`).toBe(expected);
    }
    // Spot checks against Allen's hierarchy.
    const regionsOf = (re: RegExp) =>
      new Set(paths.filter((p) => re.test(p["data-allen-acronym"])).map((p) => p["data-region"]));
    expect(regionsOf(/^(CA\d|DG)/)).toEqual(new Set(["hippocampus"])); // Ammon's horn, dentate gyrus
    expect(regionsOf(/^(ACB|LS[crv])$/)).toEqual(new Set(["striatum"])); // accumbens, lateral septum
    expect(regionsOf(/^(MO\d|SS)/)).toEqual(new Set(["cortex"])); // motor / somatosensory areas
    expect(regionsOf(/^OLF$/)).toEqual(new Set([undefined]));
  });

  it("maps every DKT parcel to at most one human lobe", () => {
    const seen = new Map<string, string>();
    for (const [lobe, parcels] of Object.entries(dktLobes.lobes)) {
      expect(REGIONS.human.some((r) => r.key === lobe), lobe).toBe(true);
      for (const p of parcels) {
        expect(seen.has(p), `${p} in ${seen.get(p)} and ${lobe}`).toBe(false);
        seen.set(p, lobe);
      }
    }
    for (const file of ["human-lateral.svg", "human-medial.svg"]) {
      const parcels = pathAttrs(svgFile(file)).filter((a) => a["data-dkt"]);
      expect(parcels.length, file).toBeGreaterThan(15);
      for (const a of parcels) {
        expect(a["data-region"] ?? null, `${file}: ${a["data-dkt"]}`).toBe(seen.get(a["data-dkt"]) ?? null);
      }
    }
    // The cingulate parcels carry the anterior cingulate datasets.
    expect(seen.get("caudalanteriorcingulate")).toBe("cingulate");
  });
});

describe("mapping datasets onto a view", () => {
  it("puts every species on the human brain through the homologous region", () => {
    const mouseCortex = ds([CORTEX], { ...mouseVivo, table_name: "mouse_cortex" });
    const mouseBrain = ds([BRAIN], { ...mouseVivo, table_name: "mouse_brain" });
    const fishBrain = ds([BRAIN], { ...fishVivo, table_name: "fish_brain" });
    const fishLarva = ds([WHOLE_ORGANISM], { ...fishVivo, table_name: "fish_larva" });
    const pfc = ds(["UBERON:0000451"], { table_name: "pfc" });
    expect(placeOnView(mouseCortex, "human")).toEqual(["cortex"]); // the "no lobe" bucket
    expect(placeOnView(mouseBrain, "human")).toEqual(["brain"]);
    expect(placeOnView(fishBrain, "human")).toEqual(["brain"]);
    expect(placeOnView(fishLarva, "human")).toEqual(["none"]);
    expect(placeOnView(pfc, "human")).toEqual(["frontal"]);
  });

  it("never spreads a cortex-only dataset over the lobes", () => {
    const c = regionTallies([ds([CORTEX], { ...mouseVivo, table_name: "m" })], "human");
    for (const k of HUMAN_LOBES) {
      expect(c.get(k)!.specific, k).toEqual([]);
      // … but lists it as broader under each lobe.
      expect(c.get(k)!.broader.map((d) => d.table_name), k).toEqual(["m"]);
    }
    expect(c.get("cortex")!.specific.map((d) => d.table_name)).toEqual(["m"]);
  });

  it("maps in-vitro intended identities to the matching human buckets", () => {
    const organoid = ds([CORTEX], { model_system: "organoid", table_name: "org" });
    const telen = ds([TELENCEPHALON], { model_system: "organoid", table_name: "telen" });
    const fore = ds([FOREBRAIN], { model_system: "ineurons", table_name: "fore" });
    const ngn2 = ds([BRAIN], { model_system: "ineurons", table_name: "ngn2" });
    const hek = ds([KIDNEY], { model_system: "cell_line", table_name: "hek" });
    expect(placeOnView(organoid, "human")).toEqual(["cortex"]);
    expect(placeOnView(telen, "human")).toEqual(["forebrain"]);
    expect(placeOnView(fore, "human")).toEqual(["forebrain"]);
    expect(placeOnView(ngn2, "human")).toEqual(["brain"]);
    expect(placeOnView(hek, "human")).toEqual(["none"]);
  });

  it("puts human lobe data on the mouse cortex, and coarse data in mouse buckets", () => {
    const gandal2022 = ds(["UBERON:0013553", "UBERON:0006101"], { table_name: "g" });
    expect(placeOnView(gandal2022, "mouse")).toEqual(["cortex"]);
    expect(placeOnView(ds([CORTEX], { model_system: "organoid" }), "mouse")).toEqual(["cortex"]);
    expect(placeOnView(ds([TELENCEPHALON], { model_system: "organoid" }), "mouse")).toEqual(["forebrain"]);
    expect(placeOnView(ds([BRAIN], fishVivo), "mouse")).toEqual(["brain"]);
    expect(placeOnView(ds([WHOLE_ORGANISM], fishVivo), "mouse")).toEqual(["none"]);
  });

  it("lists the cortex as broader for the mouse hippocampus, and buckets for what they span", () => {
    const cortex = ds([CORTEX], { ...mouseVivo, table_name: "cortex" });
    const brain = ds([BRAIN], { ...mouseVivo, table_name: "brain" });
    const c = regionTallies([cortex, brain], "mouse");
    expect(c.get("cortex")!.specific).toEqual([cortex]);
    expect(c.get("cortex")!.broader).toEqual([brain]);
    expect(c.get("hippocampus")!.specific).toEqual([]);
    expect(c.get("hippocampus")!.broader).toEqual([cortex, brain]);
    expect(c.get("midbrain")!.broader).toEqual([brain]);
    expect(c.get("brain")!.specific).toEqual([brain]);
  });

  it("does not let the hindbrain swallow the cerebellum", () => {
    const cb = ds(["UBERON:0002037"], mouseVivo);
    expect(placeOnView(cb, "mouse")).toEqual(["cerebellum"]);
  });

  it("splits tissue from in vitro for the colour and the dashed ring", () => {
    const tissue = ds([CORTEX], mouseVivo);
    const organoid = ds([CORTEX], { model_system: "organoid" });
    expect(splitInVitro([tissue, organoid])).toEqual({ tissue: [tissue], inVitro: [organoid] });
    expect(regionFill(0, 2)).not.toBe(countFill(0));
    expect(regionFill(0, 2)).not.toBe(countFill(2));
    expect(regionFill(2, 5)).toBe(countFill(2)); // colour counts tissue only
  });
});

describe("source toggle", () => {
  const humanPm = ds(["UBERON:0000451"], { table_name: "pm" });
  const mouse = ds([CORTEX], { ...mouseVivo, table_name: "mouse" });
  const fish = ds([WHOLE_ORGANISM], { ...fishVivo, table_name: "fish" });
  const organoid = ds([CORTEX], { model_system: "organoid", table_name: "org" });
  const mousePrimary = ds([CORTEX], { gene_species: "mouse", model_system: "primary_culture", table_name: "mpc" });
  const curated = ds([], { model_system: "curated", table_name: "cur" });
  const untaggedVivo = ds([], { ...mouseVivo, table_name: "untagged" });
  const all = [humanPm, mouse, fish, organoid, mousePrimary, curated, untaggedVivo];

  it("assigns each tagged dataset one source and leaves untagged ones off the page", () => {
    expect(all.map(datasetSource)).toEqual([
      "human_tissue",
      "mouse_in_vivo",
      "zebrafish_in_vivo", // organism_key wins over the human gene symbols
      "in_vitro",
      "in_vitro", // in vitro whatever the species
      null,
      null,
    ]);
  });

  it("filters by the selected sources", () => {
    expect(filterBySources(all, parseSources(undefined)).map((d) => d.table_name)).toEqual([
      "pm",
      "mouse",
      "fish",
      "org",
      "mpc",
    ]);
    expect(filterBySources(all, parseSources("in_vitro")).map((d) => d.table_name)).toEqual(["org", "mpc"]);
    expect(
      filterBySources(all, parseSources("human_tissue,zebrafish_in_vivo")).map((d) => d.table_name),
    ).toEqual(["pm", "fish"]);
  });

  it("round-trips ?sources= and treats junk / empty as all", () => {
    expect([...parseSources("")]).toEqual([...ALL_SOURCES]);
    expect([...parseSources("bogus")]).toEqual([...ALL_SOURCES]);
    expect([...parseSources("in_vitro,bogus")]).toEqual(["in_vitro"]);
    expect(sourcesParam(new Set(ALL_SOURCES))).toBeNull();
    expect(sourcesParam(new Set(["in_vitro", "human_tissue"] as const))).toBe("human_tissue,in_vitro");
    expect(sourcesParam(parseSources("mouse_in_vivo,in_vitro"))).toBe("mouse_in_vivo,in_vitro");
  });
});

describe("study kind", () => {
  // Every postmortem table, checked by hand against its config; a new
  // postmortem table fails this test until it is classified here.
  const POSTMORTEM_KINDS: Record<string, string> = {
    gandal_2018_bulk_de: "case_control",
    gandal_2022_bulk_de_per_region: "case_control",
    gandal_2022_singlecell_de: "case_control",
    psychscreen_asd_deg: "case_control",
    psychscreen_bipolar_deg: "case_control",
    psychscreen_schizophrenia_deg: "case_control",
    velmeshev_2019_degs: "case_control",
    wamsley_2024_cluster_markers: "cell_type_reference",
    psychscreen_age_deg: "age_association",
  };

  it("classifies every postmortem table", () => {
    expect(tablesWithModelSystem("postmortem")).toEqual(Object.keys(POSTMORTEM_KINDS).sort());
    for (const [table, kind] of Object.entries(POSTMORTEM_KINDS)) {
      const d = ds(["UBERON:0000451"], { table_name: table, experiment_type: "observational" });
      expect(studyKind(d), table).toBe(kind);
    }
  });

  it("only overrides tables that exist", () => {
    const tables = new Set(allConfigTables());
    for (const t of [...Object.keys(STUDY_KIND_OVERRIDES), ...Object.keys(NOT_PERTURBED_TABLES)]) {
      expect(tables.has(t), t).toBe(true);
    }
  });

  it("applies the rule to everything else", () => {
    expect(studyKind(ds([], { model_system: "in_vivo", experiment_type: "crispr_ko" }))).toBe("perturbation");
    expect(studyKind(ds([], { model_system: "organoid", experiment_type: "patient_lines" }))).toBe(
      "case_control",
    );
    expect(
      studyKind(ds([], { model_system: "organoid", experiment_type: "observational", table_name: "fleck_2023_organoid_grn" })),
    ).toBe("observational");
  });
});

describe("gene view", () => {
  it("keeps only the matched tables, then the source toggle applies", () => {
    const ko = ds([CORTEX], { ...mouseVivo, table_name: "ko" });
    const org = ds([CORTEX], { model_system: "organoid", table_name: "org" });
    const pm = ds(["UBERON:0000451"], { table_name: "pm" });
    const matched = new Map([
      ["ko", {}],
      ["org", {}],
    ]);
    const shown = datasetsWithGene([ko, org, pm], matched);
    expect(shown.map((d) => d.table_name)).toEqual(["ko", "org"]);
    expect(filterBySources(shown, parseSources("mouse_in_vivo")).map((d) => d.table_name)).toEqual(["ko"]);
    expect(regionTallies(shown, "human").get("cortex")!.specific).toEqual([ko, org]);
  });
});

describe("links", () => {
  it("builds /matrix?tables=", () => {
    expect(matrixTablesHref(["a_1", "b"])).toBe("/matrix?tables=a_1,b");
  });

  it("builds /full-datasets?region= values the page accepts", () => {
    for (const g of REGION_GROUPS) {
      const href = fullDatasetsRegionHref(g.id)!;
      const value = decodeURIComponent(href.split("region=")[1]);
      expect(value).toBe(regionFilterValue(g));
      expect(parseRegionFilterParam(value)).toBe(value);
    }
    expect(fullDatasetsRegionHref("UBERON:9999999")).toBeNull();
    expect(parseRegionFilterParam("UBERON:9999999")).toBe("");
    expect(parseRegionFilterParam(undefined)).toBe("");
    expect(parseRegionFilterParam(["UBERON:0000955"])).toBe("");
    expect(parseRegionFilterParam("exact:UBERON:0000468")).toBe("exact:UBERON:0000468");
  });
});
