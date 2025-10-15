import { TableResult } from "@/lib/table_result";
import { useState } from "react";
import DataTable from "@/components/DataTable";

export default function GeneResults({
  entrezId,
  data,
}: {
  entrezId: string | null;
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
  if (!entrezId) {
    return null;
  }
  return (
    <div
      style={{
        width: "min(1100px, 96%)",
        margin: "28px auto",
        color: "#e5e7eb",
      }}
    >
      <h2 style={{ marginBottom: 12 }}>Results for {entrezId}</h2>
      {data.length === 0 && (
        <div style={{ opacity: 0.8 }}>No results found in any dataset.</div>
      )}
      {data.map((section) => (
        <div
          key={section.tableName}
          style={{
            marginTop: 18,
            background: "#0f172a",
            border: "1px solid #334155",
            borderRadius: 12,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "12px 14px",
              borderBottom: "1px solid #334155",
              fontWeight: 600,
            }}
          >
            {section.tableName}
          </div>
          <DataTable
            columns={section.displayColumns}
            rows={
              expandedSections.has(section.tableName)
                ? section.rows
                : section.rows.slice(0, 5)
            }
          />
          {section.rows.length > 5 && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px",
                borderTop: "1px solid #334155",
                background: "#0b1220",
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
                  background: "#111827",
                  border: "1px solid #334155",
                  color: "#e5e7eb",
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
