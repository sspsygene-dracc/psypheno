import { useState, type CSSProperties, type SyntheticEvent } from "react";
import {
  EXPERIMENT_TYPE_DESCRIPTIONS,
  experimentTypeLabel,
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
  experiment: { color: "#115e59", background: "#ccfbf1" },
} as const;

/**
 * Model system, anatomy (UBERON region) and stage tags as small chips. Renders
 * nothing for an untagged dataset. `compact` shrinks them for list rows.
 * Regions past `maxRegions` collapse into a "+N more" chip that toggles them.
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
  const experiment = tags.experiment_type ?? null;
  const [expanded, setExpanded] = useState(false);
  if (systems.length === 0 && anatomy.length === 0 && !stage && !experiment) return null;

  const size: CSSProperties = compact
    ? { fontSize: 11, padding: "0 7px" }
    : { fontSize: 12, padding: "1px 9px" };
  const overflow = anatomy.length - maxRegions;
  const shown = expanded || overflow <= 0 ? anatomy : anatomy.slice(0, maxRegions);
  // The chips can sit inside a clickable row (itself a <button>), so the
  // toggle is a role="button" span rather than a nested <button>, and it keeps
  // its clicks (and mousedowns) from reaching the row.
  const toggle = (e: SyntheticEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setExpanded((v) => !v);
  };

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
      {experiment && (
        <span
          title={`Experiment type: ${
            EXPERIMENT_TYPE_DESCRIPTIONS[experiment] ?? experimentTypeLabel(experiment)
          }`}
          style={{ ...chipBase, ...size, ...PALETTE.experiment }}
        >
          {experimentTypeLabel(experiment)}
        </span>
      )}
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
      {overflow > 0 && (
        <span
          role="button"
          tabIndex={0}
          aria-expanded={expanded}
          title={expanded ? "Show fewer regions" : `Show all ${anatomy.length} regions`}
          // A row can act on mousedown (the /full-datasets picker does, to beat
          // the search box's blur): keep that from firing, and keep focus put.
          onMouseDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onClick={toggle}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") toggle(e);
          }}
          style={{
            ...chipBase,
            ...size,
            ...PALETTE.region,
            cursor: "pointer",
            fontWeight: 600,
            textDecoration: "underline",
            textUnderlineOffset: 2,
          }}
        >
          {expanded ? "Show less" : `+${overflow} more`}
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
