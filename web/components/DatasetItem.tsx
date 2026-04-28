import { useState } from "react";
import InfoTooltip from "@/components/InfoTooltip";

export type Dataset = {
  table_name: string;
  short_label: string | null;
  medium_label: string | null;
  long_label: string | null;
  description: string | null;
  gene_columns: string;
  gene_species: string;
  display_columns: string;
  scalar_columns: string;
  link_tables: string | null;
  links: string | null;
  categories: string | null;
  source: string | null;
  assay: string | null;
  organism: string | null;
  publication_first_author: string | null;
  publication_last_author: string | null;
  publication_author_count: number | null;
  publication_year: number | null;
  publication_journal: string | null;
  publication_doi: string | null;
  publication_authors?: string[];
  publication_sspsygene_grants?: string[];
};

type DatasetItemProps = {
  dataset: Dataset;
  onSelect: (tableName: string) => void;
  assayTypeLabels?: Record<string, string>;
  id?: string;
  showPublicationLink?: boolean;
  compact?: boolean;
};

export default function DatasetItem({ dataset, onSelect, assayTypeLabels = {}, id, showPublicationLink = false, compact = false }: DatasetItemProps) {
  const prettifiedName = dataset.table_name
    .replace(/_/g, " ")
    .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1));

  const heading = dataset.medium_label ?? dataset.short_label ?? prettifiedName;

  const displayColumns = dataset.display_columns
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);

  const scalarSet = new Set(
    (dataset.scalar_columns ?? "")
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean),
  );
  const geneColumnSet = new Set(
    (dataset.gene_columns ?? "")
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean),
  );
  const scalarCount = scalarSet.size;
  const geneCount = geneColumnSet.size;

  const parsedLinks =
    dataset.links
      ?.split(",")
      .map((s) => s.trim())
      .filter(Boolean) ?? [];

  const authorText = (() => {
    const first = dataset.publication_first_author;
    const last = dataset.publication_last_author;

    if (!first && !last) return "";

    const count = dataset.publication_author_count;
    if (first && last) {
      if (first === last) {
        return first;
      }
      return count != null && count > 2 ? `${first}, ..., ${last}` : `${first} & ${last}`;
    }

    if (first) {
      return `${first} et al.`;
    }

    return last ?? "";
  })();

  return (
    <div
      id={id}
      style={{
        scrollMarginTop: 16,
        width: "100%",
        padding: "16px 20px",
        borderTop: "1px solid #e5e7eb",
        background: "transparent",
        color: "#1f2937",
        transition: "background 0.15s ease",
        fontSize: 15,
        userSelect: "text",
        WebkitUserSelect: "text",
        MozUserSelect: "text",
        msUserSelect: "text",
        display: "flex",
        alignItems: "stretch",
        justifyContent: "space-between",
        boxSizing: "border-box",
        maxWidth: "100%",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLDivElement).style.background = "#f3f4f6";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLDivElement).style.background = "transparent";
      }}
    >
      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {/* Title + subtitle (suppressed in compact mode — already in collapsible bar) */}
        {!compact && (
          <div style={{ marginBottom: 2 }}>
            <div
              style={{
                fontWeight: 600,
                fontSize: 17,
                marginBottom: 2,
                color: "#111827",
              }}
            >
              {heading}
              {dataset.source && (
                <InfoTooltip text={`Source: ${dataset.source}`} size={14} />
              )}
            </div>
            {dataset.long_label && (
              <div
                style={{
                  fontSize: 15,
                  color: "#4b5563",
                  lineHeight: 1.3,
                }}
              >
                {dataset.long_label}
              </div>
            )}
          </div>
        )}
        {compact && dataset.long_label && (
          <div
            style={{
              fontSize: 16,
              fontWeight: 500,
              color: "#111827",
              lineHeight: 1.35,
            }}
          >
            {dataset.long_label}
          </div>
        )}

        {/* High‑level tags: organism/species + categories */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
            marginTop: 2,
          }}
        >
          {!compact && (dataset.organism || dataset.gene_species) && (
            <span
              style={{
                fontSize: 13,
                color: "#374151",
                backgroundColor: "#e5e7eb",
                borderRadius: 9999,
                padding: "2px 8px",
              }}
            >
              <b style={{ fontWeight: 500 }}>
                {dataset.organism ? "Organism" : "Species"}:
              </b>{" "}
              {dataset.organism ?? dataset.gene_species}
            </span>
          )}
          {!compact &&
            dataset.assay &&
            dataset.assay
              .split(",")
              .map((c) => c.trim())
              .filter(Boolean)
              .map((a) => (
                <span
                  key={`assay-${a}`}
                  style={{
                    fontSize: 13,
                    color: "#1e40af",
                    backgroundColor: "#dbeafe",
                    borderRadius: 9999,
                    padding: "2px 8px",
                    fontWeight: 500,
                  }}
                >
                  {assayTypeLabels[a] ?? a}
                </span>
              ))}
          {dataset.categories &&
            dataset.categories
              .split(",")
              .map((c) => c.trim())
              .filter(Boolean)
              .map((cat) => (
                <span
                  key={cat}
                  style={{
                    fontSize: 13,
                    color: "#374151",
                    backgroundColor: "#f3f4f6",
                    borderRadius: 9999,
                    padding: "2px 8px",
                  }}
                >
                  {cat}
                </span>
              ))}
        </div>

        {/* Description */}
        {dataset.description && (
          <div style={{ marginTop: compact ? 6 : 4 }}>
            {compact && (
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  letterSpacing: "0.05em",
                  textTransform: "uppercase",
                  color: "#6b7280",
                  marginBottom: 4,
                }}
              >
                Description
              </div>
            )}
            <div
              style={{
                fontSize: 14,
                fontWeight: 400,
                color: "#4b5563",
                lineHeight: 1.55,
              }}
            >
              {dataset.description}
            </div>
          </div>
        )}

        {/* Columns / scalars display */}
        <ColumnsList
          columns={displayColumns}
          scalarSet={scalarSet}
          geneColumnSet={geneColumnSet}
          totalScalars={scalarCount}
          totalGeneCols={geneCount}
        />

        {/* Publication line (suppressed in compact mode — parent pub card already shows it) */}
        {!compact &&
          (authorText ||
          dataset.publication_year ||
          dataset.publication_journal ||
          dataset.publication_doi) && (
          <div
            style={{
              fontSize: 14,
              color: "#6b7280",
              marginTop: 4,
            }}
          >
            <span style={{ fontWeight: 500 }}>Publication:</span> {authorText}
            {dataset.publication_year ? ` (${dataset.publication_year})` : ""}
            {dataset.publication_journal
              ? `, ${dataset.publication_journal}`
              : ""}
            {dataset.publication_doi && (
              <>
                {", "}
                <a
                  href={`https://doi.org/${dataset.publication_doi}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "#2563eb", textDecoration: "underline" }}
                >
                  DOI: {dataset.publication_doi}
                </a>
              </>
            )}
            {showPublicationLink && dataset.publication_doi && (
              <>
                {" · "}
                <a
                  href={`/publications#pub-${encodeURIComponent(
                    dataset.publication_doi,
                  )}`}
                  style={{ color: "#2563eb", textDecoration: "underline" }}
                >
                  See on Publications page
                </a>
              </>
            )}
          </div>
        )}

        {/* Dataset links (suppressed in compact mode — parent pub card aggregates them) */}
        {!compact && parsedLinks.length > 0 && (
          <div
            style={{
              fontSize: 14,
              color: "#6b7280",
              marginTop: 4,
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
              alignItems: "center",
            }}
          >
            <span style={{ fontWeight: 500 }}>Links:</span>
            {parsedLinks.map((url) => (
              <a
                key={url}
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "#2563eb", textDecoration: "underline" }}
              >
                {url}
              </a>
            ))}
          </div>
        )}
      </div>
      {!compact && (
        <div
          style={{
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            marginLeft: 16,
          }}
        >
          <button
            onClick={() => onSelect(dataset.table_name)}
            style={{
              background: "#ffffff",
              color: "#1f2937",
              border: "1px solid #d1d5db",
              borderRadius: 8,
              padding: "9px 16px",
              cursor: "pointer",
              whiteSpace: "nowrap",
              fontSize: 14,
            }}
            aria-label={`Show data for ${dataset.table_name}`}
          >
            Show data
          </button>
        </div>
      )}
    </div>
  );
}

const COL_PREVIEW_LIMIT = 6;

type ColumnsListProps = {
  columns: string[];
  scalarSet: Set<string>;
  geneColumnSet: Set<string>;
  totalScalars: number;
  totalGeneCols: number;
};

function ColumnsList({
  columns,
  scalarSet,
  geneColumnSet,
  totalScalars,
  totalGeneCols,
}: ColumnsListProps) {
  const [expanded, setExpanded] = useState(false);
  const total = columns.length;
  const overflow = total > COL_PREVIEW_LIMIT;
  const visible = expanded || !overflow ? columns : columns.slice(0, COL_PREVIEW_LIMIT);
  const hidden = overflow && !expanded ? total - COL_PREVIEW_LIMIT : 0;

  return (
    <div style={{ marginTop: 6 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexWrap: "wrap",
          fontSize: 14,
          color: "#374151",
          marginBottom: 6,
        }}
      >
        <span style={{ fontWeight: 500 }}>Columns ({total})</span>
        {totalGeneCols > 0 && (
          <ColumnLegendDot
            color="#2563eb"
            bg="#dbeafe"
            label={`${totalGeneCols} gene`}
          />
        )}
        {totalScalars > 0 && (
          <ColumnLegendDot
            color="#92400e"
            bg="#fef3c7"
            label={`${totalScalars} numeric`}
          />
        )}
        {overflow && (
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            style={{
              marginLeft: "auto",
              background: "transparent",
              border: "none",
              color: "#2563eb",
              cursor: "pointer",
              fontSize: 13,
              padding: 0,
              fontWeight: 500,
            }}
          >
            {expanded ? "Show less" : `Show all ${total}`}
          </button>
        )}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {visible.map((c) => {
          const isGene = geneColumnSet.has(c);
          const isScalar = scalarSet.has(c);
          return (
            <span
              key={c}
              title={
                isGene
                  ? "Gene identifier column"
                  : isScalar
                    ? "Numeric (scalar) column"
                    : undefined
              }
              style={{
                fontSize: 12,
                fontFamily:
                  'ui-monospace, SFMono-Regular, Menlo, Monaco, "Courier New", monospace',
                padding: "2px 8px",
                borderRadius: 4,
                background: isGene
                  ? "#dbeafe"
                  : isScalar
                    ? "#fef3c7"
                    : "#f3f4f6",
                color: isGene ? "#1e40af" : isScalar ? "#92400e" : "#374151",
                border: "1px solid",
                borderColor: isGene
                  ? "#bfdbfe"
                  : isScalar
                    ? "#fde68a"
                    : "#e5e7eb",
              }}
            >
              {c}
            </span>
          );
        })}
        {hidden > 0 && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            style={{
              fontSize: 12,
              fontFamily: "inherit",
              padding: "2px 8px",
              borderRadius: 4,
              background: "transparent",
              color: "#6b7280",
              border: "1px dashed #d1d5db",
              cursor: "pointer",
            }}
          >
            +{hidden} more
          </button>
        )}
      </div>
    </div>
  );
}

function ColumnLegendDot({
  color,
  bg,
  label,
}: {
  color: string;
  bg: string;
  label: string;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        fontSize: 12,
        color: "#6b7280",
      }}
    >
      <span
        style={{
          width: 9,
          height: 9,
          borderRadius: 2,
          background: bg,
          border: `1px solid ${color}33`,
          display: "inline-block",
        }}
      />
      {label}
    </span>
  );
}
