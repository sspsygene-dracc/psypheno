import type { CSSProperties } from "react";
import {
  MODEL_SYSTEM_DESCRIPTIONS,
  modelSystemLabel,
  stageLabel,
  type DatasetTags,
} from "@/lib/dataset-tags";

const chipBase: CSSProperties = {
  borderRadius: 9999,
  whiteSpace: "nowrap",
  lineHeight: 1.5,
};

const PALETTE = {
  model: { color: "#5b21b6", background: "#ede9fe" },
  region: { color: "#92400e", background: "#fef3c7" },
  stage: { color: "#374151", background: "#f3f4f6" },
} as const;

/**
 * Model system, anatomy (UBERON region) and stage tags as small chips. Renders
 * nothing for an untagged dataset. `compact` shrinks them for list rows.
 */
export default function DatasetTagChips({
  tags,
  compact = false,
  maxRegions = 4,
  style,
}: {
  /** A table's tags, or a paper-level union (see `modelSystems`). */
  tags: Partial<DatasetTags> & { modelSystems?: string[] };
  compact?: boolean;
  maxRegions?: number;
  style?: CSSProperties;
}) {
  const anatomy = tags.anatomy ?? [];
  const systems =
    tags.modelSystems ?? (tags.model_system ? [tags.model_system] : []);
  const stage = stageLabel({
    stage: tags.stage ?? null,
    stage_detail: tags.stage_detail ?? null,
  });
  if (systems.length === 0 && anatomy.length === 0 && !stage) return null;

  const size: CSSProperties = compact
    ? { fontSize: 11, padding: "0 7px" }
    : { fontSize: 12, padding: "1px 9px" };
  const shown = anatomy.slice(0, maxRegions);
  const hidden = anatomy.slice(maxRegions);

  return (
    <span
      style={{
        display: "inline-flex",
        flexWrap: "wrap",
        gap: 4,
        alignItems: "center",
        ...style,
      }}
    >
      {systems.map((ms) => (
        <span
          key={ms}
          title={`Model system: ${
            MODEL_SYSTEM_DESCRIPTIONS[ms] ?? modelSystemLabel(ms)
          }`}
          style={{ ...chipBase, ...size, ...PALETTE.model }}
        >
          {modelSystemLabel(ms)}
        </span>
      ))}
      {shown.map((t) => (
        <span
          key={t.id}
          title={`Anatomy: ${t.label} (${t.id})${
            tags.anatomy_column ? ` — rows split by column "${tags.anatomy_column}"` : ""
          }`}
          style={{ ...chipBase, ...size, ...PALETTE.region }}
        >
          {t.label}
        </span>
      ))}
      {hidden.length > 0 && (
        <span
          title={hidden.map((t) => `${t.label} (${t.id})`).join("\n")}
          style={{ ...chipBase, ...size, ...PALETTE.region }}
        >
          +{hidden.length} more
        </span>
      )}
      {stage && (
        <span
          title="Developmental stage / culture age"
          style={{ ...chipBase, ...size, ...PALETTE.stage }}
        >
          {stage}
        </span>
      )}
    </span>
  );
}
