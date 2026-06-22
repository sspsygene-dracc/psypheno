import React from "react";

/**
 * The three dataset-level restrictor dimensions, mirrored from the
 * `data_tables` metadata columns `assay`, `condition`, and `organism_key`.
 * A `null` value on any axis means "All" (no restriction on that axis).
 */
export type DatasetRestriction = {
  assay: string | null;
  condition: string | null;
  organism: string | null;
};

export const EMPTY_RESTRICTION: DatasetRestriction = {
  assay: null,
  condition: null,
  organism: null,
};

const radioLabelStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  cursor: "pointer",
  color: "#4b5563",
  whiteSpace: "nowrap",
  fontSize: 14,
};

const filterLabelStyle: React.CSSProperties = {
  fontWeight: 600,
  color: "#374151",
  whiteSpace: "nowrap",
};

const rowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 14,
  flexWrap: "wrap",
};

/**
 * Controlled assay / condition / organism dataset restrictor. Extracted from
 * `/most-significant` (#191) so the home page and the cross-study ranking
 * share one source of truth.
 *
 * The `available*` props are the values that actually occur in the datasets
 * under consideration (for the home page: the datasets that have data for the
 * queried gene; for `/most-significant`: the combined-p-value groups). An axis
 * with no available values renders nothing, and when all three are empty the
 * whole component renders nothing.
 */
export default function DatasetRestrictor({
  availableAssays,
  availableConditions,
  availableOrganisms,
  assayTypeLabels,
  conditionTypeLabels,
  organismTypeLabels,
  value,
  onChange,
  idPrefix = "restrictor",
}: {
  availableAssays: string[];
  availableConditions: string[];
  availableOrganisms: string[];
  assayTypeLabels: Record<string, string>;
  conditionTypeLabels: Record<string, string>;
  organismTypeLabels: Record<string, string>;
  value: DatasetRestriction;
  onChange: (next: DatasetRestriction) => void;
  idPrefix?: string;
}) {
  const hasAny =
    availableAssays.length > 0 ||
    availableConditions.length > 0 ||
    availableOrganisms.length > 0;
  if (!hasAny) return null;

  const renderRow = (
    label: string,
    name: string,
    available: string[],
    selected: string | null,
    labels: Record<string, string>,
    set: (v: string | null) => void,
  ) => {
    if (available.length === 0) return null;
    return (
      <div style={rowStyle}>
        <span style={filterLabelStyle}>{label}:</span>
        <label style={radioLabelStyle}>
          <input
            type="radio"
            name={`${idPrefix}-${name}`}
            checked={selected === null}
            onChange={() => set(null)}
          />
          All
        </label>
        {available.map((key) => (
          <label key={key} style={radioLabelStyle}>
            <input
              type="radio"
              name={`${idPrefix}-${name}`}
              checked={selected === key}
              onChange={() => set(key)}
            />
            {labels[key] || key}
          </label>
        ))}
      </div>
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {renderRow(
        "Assay type",
        "assay",
        availableAssays,
        value.assay,
        assayTypeLabels,
        (v) => onChange({ ...value, assay: v }),
      )}
      {renderRow(
        "Condition",
        "condition",
        availableConditions,
        value.condition,
        conditionTypeLabels,
        (v) => onChange({ ...value, condition: v }),
      )}
      {renderRow(
        "Organism",
        "organism",
        availableOrganisms,
        value.organism,
        organismTypeLabels,
        (v) => onChange({ ...value, organism: v }),
      )}
    </div>
  );
}
