import React from "react";

export type Dataset = {
  table_name: string;
  short_label: string | null;
  long_label: string | null;
  description: string | null;
  gene_columns: string;
  gene_species: string;
  display_columns: string;
  scalar_columns: string;
  link_tables: string | null;
  links: string | null;
  categories: string | null;
  organism: string | null;
  publication_first_author: string | null;
  publication_last_author: string | null;
  publication_year: number | null;
  publication_journal: string | null;
  publication_doi: string | null;
};

type DatasetItemProps = {
  dataset: Dataset;
  onSelect: (tableName: string) => void;
};

export default function DatasetItem({ dataset, onSelect }: DatasetItemProps) {
  const prettifiedName = dataset.table_name
    .replace(/_/g, " ")
    .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1));

  const heading = dataset.short_label ?? prettifiedName;

  const displayColumns = dataset.display_columns
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);

  const maxColumnsToShow = 4;
  const visibleColumns = displayColumns.slice(0, maxColumnsToShow);
  const remainingColumnCount = displayColumns.length - visibleColumns.length;

  const authorText = (() => {
    const first = dataset.publication_first_author;
    const last = dataset.publication_last_author;

    if (!first && !last) return "";

    if (first && last) {
      if (first === last) {
        return first;
      }
      return `${first} & ${last}`;
    }

    if (first) {
      return `${first} et al.`;
    }

    return last ?? "";
  })();

  return (
    <div
      style={{
        width: "100%",
        padding: "16px 20px",
        borderTop: "1px solid #e5e7eb",
        background: "transparent",
        color: "#1f2937",
        transition: "background 0.15s ease",
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
        {/* Title + subtitle */}
        <div style={{ marginBottom: 2 }}>
          <div
            style={{
              fontWeight: 600,
              fontSize: 15,
              marginBottom: 2,
              color: "#111827",
            }}
          >
            {heading}
          </div>
          {dataset.long_label && (
            <div
              style={{
                fontSize: 13,
                color: "#4b5563",
                lineHeight: 1.3,
              }}
            >
              {dataset.long_label}
            </div>
          )}
        </div>

        {/* High‑level tags: organism/species + categories */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
            marginTop: 2,
          }}
        >
          {(dataset.organism || dataset.gene_species) && (
            <span
              style={{
                fontSize: 11,
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
          {dataset.categories &&
            dataset.categories
              .split(",")
              .map((c) => c.trim())
              .filter(Boolean)
              .map((cat) => (
                <span
                  key={cat}
                  style={{
                    fontSize: 11,
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
          <div
            style={{
              fontSize: 13,
              color: "#4b5563",
              marginTop: 4,
            }}
          >
            {dataset.description}
          </div>
        )}

        {/* Structured meta rows */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            marginTop: 6,
            fontSize: 12,
            color: "#6b7280",
          }}
        >
          {/* Columns summary */}
          <div style={{ minWidth: 0 }}>
            <span style={{ fontWeight: 500 }}>
              Columns ({displayColumns.length}):
            </span>{" "}
            <span>
              {visibleColumns.join(", ")}
              {remainingColumnCount > 0
                ? `, +${remainingColumnCount} more`
                : ""}
            </span>
          </div>

          {/* Scalar columns, if present */}
          {dataset.scalar_columns && (
            <div style={{ minWidth: 0 }}>
              <span style={{ fontWeight: 500 }}>Scalars:</span>{" "}
              <span>{dataset.scalar_columns}</span>
            </div>
          )}
        </div>

        {/* Publication line */}
        {(authorText ||
          dataset.publication_year ||
          dataset.publication_journal ||
          dataset.publication_doi) && (
          <div
            style={{
              fontSize: 12,
              color: "#6b7280",
              marginTop: 4,
            }}
          >
            <span style={{ fontWeight: 500 }}>Publication:</span> {authorText}
            {dataset.publication_year ? ` (${dataset.publication_year})` : ""}
            {dataset.publication_journal
              ? `, ${dataset.publication_journal}`
              : ""}
            {dataset.publication_doi ? `, DOI: ${dataset.publication_doi}` : ""}
          </div>
        )}
      </div>
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
            padding: "8px 14px",
            cursor: "pointer",
            whiteSpace: "nowrap",
            fontSize: 13,
          }}
          aria-label={`Show first 100 rows of ${dataset.table_name}`}
        >
          Show first 100 rows
        </button>
      </div>
    </div>
  );
}
