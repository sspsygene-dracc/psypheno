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

  return (
    <div
      style={{
        width: "100%",
        padding: "16px",
        borderTop: "1px solid #e5e7eb",
        background: "transparent",
        color: "#1f2937",
        transition: "background 0.2s ease",
        userSelect: "text",
        WebkitUserSelect: "text",
        MozUserSelect: "text",
        msUserSelect: "text",
        display: "flex",
        flexWrap: "wrap",
        gap: 12,
        alignItems: "flex-start",
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
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>{heading}</div>
        {dataset.long_label && (
          <div
            style={{
              fontSize: 14,
              color: "#4b5563",
              marginBottom: 4,
            }}
          >
            {dataset.long_label}
          </div>
        )}
        <div style={{ fontSize: 14, color: "#6b7280" }}>
          <b>{dataset.display_columns.split(",").length} Columns:</b>{" "}
          {dataset.display_columns.split(",").join(", ")}
        </div>
        <div
          style={{
            fontSize: 13,
            color: "#6b7280",
            marginTop: 4,
          }}
        >
          {dataset.organism && (
            <span>
              <b>Organism:</b> {dataset.organism}
            </span>
          )}
          {!dataset.organism && dataset.gene_species && (
            <span>
              <b>Species:</b> {dataset.gene_species}
            </span>
          )}
        </div>
        {dataset.categories && (
          <div
            style={{
              fontSize: 12,
              color: "#4b5563",
              marginTop: 4,
              display: "flex",
              flexWrap: "wrap",
              gap: 6,
            }}
          >
            {dataset.categories
              .split(",")
              .map((c) => c.trim())
              .filter(Boolean)
              .map((cat) => (
                <span
                  key={cat}
                  style={{
                    backgroundColor: "#f3f4f6",
                    borderRadius: 9999,
                    padding: "2px 8px",
                  }}
                >
                  {cat}
                </span>
              ))}
          </div>
        )}
        {dataset.description && (
          <div
            style={{
              fontSize: 14,
              color: "#6b7280",
              marginTop: 6,
            }}
          >
            <b>Description:</b> {dataset.description}
          </div>
        )}
        {(dataset.publication_first_author ||
          dataset.publication_year ||
          dataset.publication_journal ||
          dataset.publication_doi) && (
          <div
            style={{
              fontSize: 13,
              color: "#6b7280",
              marginTop: 4,
            }}
          >
            <b>Publication:</b>{" "}
            {dataset.publication_first_author
              ? `${dataset.publication_first_author}${
                  dataset.publication_last_author
                    ? " & " + dataset.publication_last_author
                    : " et al."
                }`
              : ""}
            {dataset.publication_year ? ` (${dataset.publication_year})` : ""}
            {dataset.publication_journal
              ? `, ${dataset.publication_journal}`
              : ""}
          </div>
        )}
      </div>
      <div style={{ flexShrink: 0 }}>
        <button
          onClick={() => onSelect(dataset.table_name)}
          style={{
            background: "#ffffff",
            color: "#1f2937",
            border: "1px solid #d1d5db",
            borderRadius: 8,
            padding: "8px 12px",
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
          aria-label={`Show first 100 rows of ${dataset.table_name}`}
        >
          Show first 100 rows
        </button>
      </div>
    </div>
  );
}
