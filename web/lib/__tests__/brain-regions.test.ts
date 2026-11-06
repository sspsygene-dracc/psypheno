import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  CURATED_PART_OF,
  REGIONS,
  REGION_SPECIES,
  TRAY_GROUPS,
  countFill,
  isBroader,
  isSpecific,
  placement,
  regionCounts,
  studyKind,
  trayCoversRegion,
  trayGroupOf,
  trayGroups,
  unplacedTissue,
  type RegionDataset,
  type RegionSpecies,
} from "@/lib/brain-regions";
import { matchesRegionFilter } from "@/lib/dataset-tags";
import { REGION_DRAWINGS, svgRegionKeys } from "@/lib/region-drawings";
import allenMap from "@/lib/regions/allen-mouse-regions.json";
import dktLobes from "@/lib/regions/dkt-lobes.json";

const drawingKeys = (src: string) =>
  svgRegionKeys(fs.readFileSync(path.resolve(__dirname, "../../public", `.${src}`), "utf8"));

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
function ds(
  ids: string[],
  extra: Partial<RegionDataset> = {},
): RegionDataset {
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

/** Every UBERON id written in a dataset config (anatomy tags). */
function configAnatomyIds(): string[] {
  const dir = path.join(REPO, "data/datasets");
  const ids = new Set<string>();
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name, "config.yaml");
    if (!fs.existsSync(p)) continue;
    for (const m of fs.readFileSync(p, "utf8").matchAll(/^\s*-\s*(UBERON:\d+)/gm)) ids.add(m[1]);
  }
  return [...ids].sort();
}

const HUMAN_LOBES = ["frontal", "parietal", "temporal", "occipital", "cingulate"];
const region = (species: RegionSpecies, key: string) =>
  REGIONS[species].find((r) => r.key === key)!;

describe("region map", () => {
  it("references only UBERON ids that exist in the vendored list", () => {
    for (const s of REGION_SPECIES) {
      for (const r of REGIONS[s]) {
        for (const id of [r.uberon, ...r.match, ...(r.exact ?? []), ...r.within]) {
          expect(UBERON.has(id), `${s}/${r.key}: ${id}`).toBe(true);
        }
      }
    }
    for (const [k, ids] of Object.entries(CURATED_PART_OF)) {
      expect(UBERON.has(k), k).toBe(true);
      for (const id of ids) expect(UBERON.has(id), `${k} -> ${id}`).toBe(true);
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
    const g2018 = ds(["UBERON:0001870", "UBERON:0016538"]);
    expect(HUMAN_LOBES.filter((k) => isSpecific(g2018, region("human", k)))).toEqual([
      "frontal",
      "temporal",
    ]);
  });

  it("applies the curated map to /full-datasets' Region filter too", () => {
    expect(matchesRegionFilter(ds(["UBERON:0006472"]), "UBERON:0001870")).toBe(true); // BA6
    expect(matchesRegionFilter(ds(["UBERON:0006472"]), "UBERON:0016538")).toBe(false);
  });

  it("places every tagged anatomy term somewhere on the page", () => {
    // Terms that are deliberately not drawn: kidney (HEK293T cell line).
    const notDrawn = new Set(["UBERON:0002113"]);
    for (const id of configAnatomyIds()) {
      if (notDrawn.has(id)) continue;
      const d = ds([id]);
      const hit = REGION_SPECIES.some((s) =>
        REGIONS[s].some((r) => isSpecific(d, r) || isBroader(d, r)),
      );
      expect(hit, `${id} (${UBERON.get(id)?.label})`).toBe(true);
    }
  });

  it("vendors drawings that are safe to inline", () => {
    for (const s of REGION_SPECIES) {
      for (const d of REGION_DRAWINGS[s]) {
        const text = fs.readFileSync(path.resolve(__dirname, "../../public", `.${d.src}`), "utf8");
        expect(text, d.src).toMatch(/^<svg[^>]*viewBox=/);
        expect(text, d.src).not.toMatch(/<script|\son\w+=|href="(?!#)|url\((?!#)/i);
      }
    }
  });

  it("draws every non-pseudo region, and only known regions", () => {
    for (const s of REGION_SPECIES) {
      const drawn = new Set(REGION_DRAWINGS[s].flatMap((d) => drawingKeys(d.src)));
      for (const r of REGIONS[s]) {
        if (!r.pseudo) expect(drawn.has(r.key), `${s}/${r.key}`).toBe(true);
      }
      for (const k of drawn) {
        expect(REGIONS[s].some((r) => r.key === k), `${s}: shape ${k}`).toBe(true);
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
    for (const r of REGIONS.mouse) if (!r.pseudo) expect(ruled.has(r.key), r.key).toBe(true);
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

describe("matching", () => {
  it("separates specific from broader datasets", () => {
    const cortex = ds(["UBERON:0000956"], { gene_species: "mouse", model_system: "in_vivo" });
    const wholeBrain = ds(["UBERON:0000955"], { gene_species: "mouse", model_system: "in_vivo" });
    const c = regionCounts([cortex, wholeBrain], "mouse");
    expect(c.get("cortex")!.specific).toEqual([cortex]);
    expect(c.get("cortex")!.broader).toEqual([wholeBrain]);
    // Hippocampus lies within the cortex: a cortex dataset is broader there.
    expect(c.get("hippocampus")!.specific).toEqual([]);
    expect(c.get("hippocampus")!.broader).toEqual([cortex, wholeBrain]);
    expect(c.get("striatum")!.broader).toEqual([wholeBrain]);
    // The whole-brain dataset is listed under the outline, not painted.
    expect(c.get("whole")!.specific).toEqual([wholeBrain]);
  });

  it("does not let the hindbrain swallow the cerebellum", () => {
    const cb = ds(["UBERON:0002037"], { gene_species: "mouse", model_system: "in_vivo" });
    expect(isSpecific(cb, region("mouse", "cerebellum"))).toBe(true);
    expect(isSpecific(cb, region("mouse", "hindbrain"))).toBe(false);
  });

  it("puts whole-larva screens on the larva and brain maps on the brain", () => {
    const fish = { gene_species: "zebrafish", model_system: "in_vivo" };
    const behaviour = ds(["UBERON:0000468"], fish);
    const pERK = ds(["UBERON:0000955"], fish);
    const c = regionCounts([behaviour, pERK], "zebrafish");
    expect(c.get("larva")!.specific).toEqual([behaviour]);
    expect(c.get("brain")!.specific).toEqual([pERK]);
    expect(c.get("brain")!.broader).toEqual([behaviour]);
    expect(c.get("larva")!.broader).toEqual([]);
  });

  it("uses the organism key over the gene species", () => {
    // A zebrafish screen keyed by human gene symbols.
    const d = ds(["UBERON:0000468"], {
      gene_species: "human",
      organism_key: ["zebrafish"],
      model_system: "in_vivo",
    });
    expect(regionCounts([d], "zebrafish").get("larva")!.specific).toEqual([d]);
    expect(unplacedTissue([d], "human")).toEqual([]);
    expect(
      Array.from(regionCounts([d], "human").values()).every(
        (v) => v.specific.length === 0 && v.broader.length === 0,
      ),
    ).toBe(true);
  });

  it("keeps in-vitro and curated datasets off the drawings", () => {
    const organoid = ds(["UBERON:0000956"], { model_system: "organoid" });
    const curated = ds([], { model_system: "curated" });
    expect(placement(organoid)).toBe("in_vitro");
    expect(placement(curated)).toBe("excluded");
    // No anatomy tag at all: off the page whatever the model system.
    expect(placement(ds([], { model_system: "in_vivo" }))).toBe("excluded");
    expect(placement(ds([], { model_system: "organoid" }))).toBe("excluded");
    expect(regionCounts([organoid, curated], "human").get("frontal")!.specific).toEqual([]);
  });
});

describe("in-vitro tray", () => {
  it("groups by intended identity", () => {
    expect(trayGroupOf(ds(["UBERON:0000956"], { model_system: "organoid" })).key).toBe("cortical");
    expect(trayGroupOf(ds(["UBERON:0001890"], { model_system: "ineurons" })).key).toBe("forebrain");
    expect(trayGroupOf(ds(["UBERON:0001893"], { model_system: "organoid" })).key).toBe("forebrain");
    expect(trayGroupOf(ds(["UBERON:0000955"], { model_system: "ineurons" })).key).toBe("brain");
    expect(trayGroupOf(ds(["UBERON:0002113"], { model_system: "cell_line" })).key).toBe("non_neural");
    const g = trayGroups([
      ds(["UBERON:0000956"], { model_system: "organoid" }),
      ds(["UBERON:0000956"], { model_system: "postmortem" }),
    ]);
    expect(g.get("cortical")).toHaveLength(1);
  });

  it("outlines the regions an identity covers", () => {
    const [cortical, forebrain, brain, nonNeural] = TRAY_GROUPS;
    const human = (g: typeof cortical) =>
      REGIONS.human.filter((r) => !r.pseudo && trayCoversRegion(g, r)).map((r) => r.key);
    expect(human(cortical)).toEqual([...HUMAN_LOBES, "insula"]);
    expect(human(nonNeural)).toEqual([]);
    const mouse = (g: typeof cortical) =>
      REGIONS.mouse.filter((r) => !r.pseudo && trayCoversRegion(g, r)).map((r) => r.key);
    expect(mouse(forebrain)).not.toContain("midbrain");
    expect(mouse(forebrain)).toContain("striatum");
    expect(mouse(brain)).toContain("midbrain");
  });
});

describe("study kind and colour", () => {
  it("tells postmortem case-control from perturbation", () => {
    expect(studyKind(ds([], { model_system: "postmortem", experiment_type: "observational" }))).toBe(
      "case_control",
    );
    expect(studyKind(ds([], { model_system: "in_vivo", experiment_type: "crispr_ko" }))).toBe(
      "perturbation",
    );
    expect(studyKind(ds([], { model_system: "organoid", experiment_type: "patient_lines" }))).toBe(
      "case_control",
    );
    expect(studyKind(ds([], { model_system: "organoid", experiment_type: "observational" }))).toBe(
      "observational",
    );
  });

  it("bins counts into a light-to-dark ramp", () => {
    expect(countFill(0)).not.toBe(countFill(1));
    expect(countFill(3)).toBe(countFill(4));
    expect(countFill(50)).toBe(countFill(5));
  });
});
