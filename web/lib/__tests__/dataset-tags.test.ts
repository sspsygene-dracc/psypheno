import { describe, expect, it } from "vitest";
import {
  matchesRegion,
  parseTags,
  stageLabel,
  tagSelectSql,
} from "@/lib/dataset-tags";

describe("dataset tags", () => {
  it("parses the stored columns", () => {
    const tags = parseTags({
      model_system: "postmortem",
      anatomy: JSON.stringify([{ id: "UBERON:0001950", label: "neocortex" }]),
      anatomy_closure: JSON.stringify(["UBERON:0001950", "UBERON:0000955"]),
      anatomy_column: null,
      stage: "adult",
      stage_detail: null,
    });
    expect(tags.anatomy).toEqual([{ id: "UBERON:0001950", label: "neocortex" }]);
    expect(matchesRegion(tags.anatomy_closure, "UBERON:0000955")).toBe(true);
    expect(matchesRegion(tags.anatomy_closure, "UBERON:0002113")).toBe(false);
  });

  it("treats malformed / missing JSON as untagged", () => {
    const tags = parseTags({
      model_system: null,
      anatomy: "not json",
      anatomy_closure: null,
      stage: null,
      stage_detail: null,
    });
    expect(tags.anatomy).toEqual([]);
    expect(tags.anatomy_closure).toEqual([]);
    expect(tags.anatomy_column).toBeNull();
  });

  it("formats the stage chip", () => {
    expect(stageLabel({ stage: "in_vitro", stage_detail: "NGN2 day 28" })).toBe(
      "In vitro · NGN2 day 28",
    );
    expect(stageLabel({ stage: null, stage_detail: null })).toBeNull();
  });

  it("NULL-aliases columns the DB predates", () => {
    const sql = tagSelectSql((c) => c === "model_system");
    expect(sql).toContain("model_system,");
    expect(sql).toContain("NULL AS anatomy_closure");
  });
});
