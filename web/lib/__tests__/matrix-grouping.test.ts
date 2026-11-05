import { describe, expect, it } from "vitest";
import type { MatrixColumn, MatrixDatasetGroups } from "@/lib/collated-matrix-types";
import {
  bandRowHeight,
  datasetBands,
  groupColumns,
  NONE_KEY,
  wrappedLineCount,
} from "@/lib/matrix-grouping";

function col(section: string, table: string, label: string): MatrixColumn {
  return {
    section,
    key: `${section}:${table}:${label}`,
    label,
    metric: "neglog_q",
    columnIsGene: true,
    nSigGroups: 2,
    sourceTable: table,
    sourceLabel: `${table} 2026`,
    sourceMediumLabel: null,
    sourceCitation: null,
  };
}

const sectionLabel = new Map([
  ["expression", "RNA expression"],
  ["behavior", "Behavioral"],
]);

// API order: by modality, then dataset — the order every grouping starts from.
const columns: MatrixColumn[] = [
  col("expression", "cui", "A"),
  col("expression", "cui", "B"),
  col("expression", "shi", "C"),
  col("expression", "wang", "D"),
  // A compact single-gene study's condition block.
  col("expression", "solo", "__condition__:0"),
  col("expression", "solo", "__condition__:1"),
  col("behavior", "fish", "E"),
  col("behavior", "cui", "F"),
];

const groups: Record<string, MatrixDatasetGroups> = {
  cui: { modelSystem: "ineurons", region: "forebrain", species: ["human"], experimentType: "crispr_ko" },
  shi: { modelSystem: "in_vivo", region: "brain", species: ["mouse"], experimentType: "crispr_ko" },
  wang: { modelSystem: "cell_line", region: "other_tissue", species: ["human"], experimentType: "overexpression" },
  solo: { modelSystem: "ineurons", region: "cerebral_cortex", species: ["human"], experimentType: "crispri" },
  fish: { modelSystem: "in_vivo", region: "whole_organism", species: ["zebrafish"], experimentType: "crispr_ko" },
};

const labels = (cs: MatrixColumn[]) => cs.map((c) => c.label);

describe("groupColumns", () => {
  it("modality keeps the API order and bands the sections", () => {
    const { columns: out, groups: bands } = groupColumns(columns, "modality", sectionLabel, groups);
    expect(out).toEqual(columns);
    expect(bands.map((b) => [b.label, b.startCol, b.span])).toEqual([
      ["RNA expression", 0, 6],
      ["Behavioral", 6, 2],
    ]);
  });

  it("model system: groups in vocabulary order, columns stable inside a group", () => {
    const { columns: out, groups: bands } = groupColumns(columns, "model_system", sectionLabel, groups);
    // MODEL_SYSTEM order: in_vivo, ..., ineurons, ..., cell_line.
    expect(bands.map((b) => [b.key, b.label, b.startCol, b.span])).toEqual([
      ["in_vivo", "In vivo", 0, 2],
      ["ineurons", "iNeurons", 2, 5],
      ["cell_line", "Cell line", 7, 1],
    ]);
    // Within iNeurons: cui's expression columns, the compact block, then cui's
    // behavior column — the incoming (modality, dataset) order.
    expect(labels(out)).toEqual([
      "C",
      "E",
      "A",
      "B",
      "__condition__:0",
      "__condition__:1",
      "F",
      "D",
    ]);
  });

  it("keeps every column exactly once and a table's columns together per modality", () => {
    for (const key of ["model_system", "region", "species", "experiment_type"] as const) {
      const { columns: out, groups: bands } = groupColumns(columns, key, sectionLabel, groups);
      expect([...out].sort((a, b) => a.key.localeCompare(b.key))).toEqual(
        [...columns].sort((a, b) => a.key.localeCompare(b.key))
      );
      expect(bands.reduce((n, b) => n + b.span, 0)).toBe(columns.length);
      // Bands tile the columns without gaps.
      bands.forEach((b, i) => {
        expect(b.startCol).toBe(i === 0 ? 0 : bands[i - 1].startCol + bands[i - 1].span);
      });
    }
  });

  it("region: coarse-region order", () => {
    const { groups: bands } = groupColumns(columns, "region", sectionLabel, groups);
    expect(bands.map((b) => b.key)).toEqual([
      "cerebral_cortex",
      "forebrain",
      "brain",
      "whole_organism",
      "other_tissue",
    ]);
    expect(bands[0].label).toBe("Cerebral cortex");
  });

  it("species: organism order, mixes after their first species", () => {
    const g = { ...groups, wang: { ...groups.wang, species: ["mouse", "human"] } };
    const { groups: bands } = groupColumns(columns, "species", sectionLabel, g);
    expect(bands.map((b) => [b.key, b.label])).toEqual([
      ["human", "Human"],
      ["human+mouse", "Human + Mouse"],
      ["mouse", "Mouse"],
      ["zebrafish", "Zebrafish"],
    ]);
  });

  it("experiment type: vocabulary order", () => {
    const { groups: bands } = groupColumns(columns, "experiment_type", sectionLabel, groups);
    expect(bands.map((b) => [b.label, b.span])).toEqual([
      ["CRISPR knockout", 5],
      ["CRISPRi", 2],
      ["Overexpression", 1],
    ]);
  });

  it("untagged tables (or no tags at all from an older API) go last", () => {
    const partial = { cui: groups.cui };
    const { groups: bands } = groupColumns(columns, "experiment_type", sectionLabel, partial);
    expect(bands.map((b) => b.key)).toEqual(["crispr_ko", NONE_KEY]);
    expect(bands[1].label).toBe("Experiment type not tagged");

    const none = groupColumns(columns, "model_system", sectionLabel, undefined);
    expect(none.groups).toHaveLength(1);
    expect(none.groups[0].key).toBe(NONE_KEY);
    expect(none.columns).toEqual(columns);
  });

  it("unknown tag values sort after known ones, before untagged", () => {
    const { groups: bands } = groupColumns(columns, "experiment_type", sectionLabel, {
      cui: groups.cui,
      wang: { ...groups.wang, experimentType: "base_editing" },
    });
    expect(bands.map((b) => [b.key, b.label])).toEqual([
      ["crispr_ko", "CRISPR knockout"],
      ["base_editing", "base_editing"],
      [NONE_KEY, "Experiment type not tagged"],
    ]);
  });

  it("follows hidden datasets (groups only what it is given)", () => {
    const visible = columns.filter((c) => c.sourceTable !== "wang");
    const { groups: bands } = groupColumns(visible, "model_system", sectionLabel, groups);
    expect(bands.map((b) => b.key)).toEqual(["in_vivo", "ineurons"]);
  });
});

describe("datasetBands", () => {
  it("one band per run of a table within a modality", () => {
    const { columns: out } = groupColumns(columns, "model_system", sectionLabel, groups);
    const bands = datasetBands(out, sectionLabel, { withModality: true });
    expect(bands.map((b) => [b.bandLabel, b.startCol, b.span])).toEqual([
      ["RNA expression · shi 2026", 0, 1],
      ["Behavioral · fish 2026", 1, 1],
      ["RNA expression · cui 2026", 2, 2],
      ["RNA expression · solo 2026", 4, 2],
      ["Behavioral · cui 2026", 6, 1],
      ["RNA expression · wang 2026", 7, 1],
    ]);
    expect(new Set(bands.map((b) => b.gkey)).size).toBe(bands.length);
  });

  it("drops the modality under a modality group row", () => {
    const bands = datasetBands(columns, sectionLabel, { withModality: false });
    expect(bands.map((b) => b.bandLabel)).toEqual([
      "cui 2026",
      "shi 2026",
      "wang 2026",
      "solo 2026",
      "fish 2026",
      "cui 2026",
    ]);
  });
});

describe("band row height", () => {
  const opts = { chromeW: 10, charPx: 6, lineH: 13, padV: 9, minH: 22, maxH: 50 };

  it("one line for a wide band, more when a narrow band wraps, clamped", () => {
    expect(bandRowHeight([{ label: "In vivo", span: 20 }], 17, opts)).toBe(22);
    // 2 columns = 34px - 10 chrome = 24px → 4 chars per line.
    expect(bandRowHeight([{ label: "Patient-derived lines", span: 2 }], 17, opts)).toBe(50);
    expect(bandRowHeight([{ label: "Cell line", span: 3 }], 17, opts)).toBe(2 * 13 + 9);
  });

  it("wrappedLineCount wraps on words", () => {
    expect(wrappedLineCount("Behavioral · Fernandez Garcia 2026", 10)).toBe(5);
    expect(wrappedLineCount("In vivo", 40)).toBe(1);
  });
});
