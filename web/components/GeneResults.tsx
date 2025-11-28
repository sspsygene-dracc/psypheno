import { TableResult } from "@/lib/table_result";
import { useState } from "react";
import DataTable from "@/components/DataTable";

export default function GeneResults({
  geneDisplayName,
  data,
}: {
  geneDisplayName: string | null;
  data: TableResult[];
}) {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set()
  );

  const toggleSection = (name: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };
  if (!geneDisplayName) {
    return null;
  }
  return (
    <div
      style={{
        width: "min(1100px, 96%)",
        margin: "28px auto",
        color: "#1f2937",
      }}
    >
      <h2 style={{ marginBottom: 12 }}>Results for {geneDisplayName}</h2>
      {data.length === 0 && (
        <div style={{ opacity: 0.8 }}>No results found in any dataset.</div>
      )}
      {data.map((section) => (
        <div
          key={section.tableName}
          style={{
            marginTop: 18,
            background: "#ffffff",
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "12px 14px",
              borderBottom: "1px solid #e5e7eb",
              fontWeight: 600,
            }}
          >
              {section.shortLabel ??
                section.tableName
                  .replace(/_/g, " ")
                  .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1))}
          </div>
          {section.description && (
            <div
              style={{ padding: "10px 14px", color: "#6b7280", fontSize: 14 }}
            >
              {section.description}
            </div>
          )}
          <DataTable
            columns={section.displayColumns}
            rows={
              expandedSections.has(section.tableName)
                ? section.rows
                : section.rows.slice(0, 5)
            }
            showSummary={false}
          />
          {section.rows.length > 5 && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px",
                borderTop: "1px solid #e5e7eb",
                background: "#f9fafb",
              }}
            >
              <div style={{ opacity: 0.8, fontSize: 13 }}>
                {expandedSections.has(section.tableName)
                  ? `Showing all ${section.rows.length}`
                  : `Showing 5 of ${section.rows.length}`}
              </div>
              <button
                onClick={() => toggleSection(section.tableName)}
                style={{
                  padding: "8px 12px",
                  background: "#ffffff",
                  border: "1px solid #d1d5db",
                  color: "#1f2937",
                  borderRadius: 10,
                  fontSize: 14,
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                {expandedSections.has(section.tableName)
                  ? "Collapse"
                  : "Expand"}
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
