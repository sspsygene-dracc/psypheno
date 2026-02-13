import { TableResult } from "@/lib/table_result";
import { useState, useEffect } from "react";
import DataTable from "@/components/DataTable";
import InfoTooltip from "@/components/InfoTooltip";

const formatTableName = (section: TableResult) =>
  section.shortLabel ??
  section.tableName
    .replace(/_/g, " ")
    .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1));

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
  const [showToc, setShowToc] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 900px)");
    setShowToc(mql.matches);
    const handler = (e: MediaQueryListEvent) => setShowToc(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

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

  const scrollTo = (tableName: string) => {
    document
      .getElementById(`table-${tableName}`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div
      style={{
        width: showToc ? "min(1400px, 96%)" : "min(1100px, 96%)",
        margin: "28px auto",
        color: "#1f2937",
        display: "flex",
        gap: 24,
        alignItems: "flex-start",
      }}
    >
      {showToc && data.length > 0 && (
        <nav
          style={{
            width: 220,
            flexShrink: 0,
            position: "sticky",
            top: 20,
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            padding: "14px 0",
            marginTop: 50,
          }}
        >
          <div
            style={{
              padding: "0 14px 10px",
              fontWeight: 600,
              fontSize: 13,
              color: "#6b7280",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            Datasets
          </div>
          {data.map((section) => (
            <button
              key={section.tableName}
              onClick={() => scrollTo(section.tableName)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "8px 14px",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                fontSize: 14,
                color: "#2563eb",
                lineHeight: 1.4,
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "#e5e7eb")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "transparent")
              }
            >
              {formatTableName(section)}
            </button>
          ))}
        </nav>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <h2 style={{ marginBottom: 12 }}>Results for {geneDisplayName}</h2>
        {data.length === 0 && (
          <div style={{ opacity: 0.8 }}>No results found in any dataset.</div>
        )}
        {data.map((section) => (
          <div
            key={section.tableName}
            id={`table-${section.tableName}`}
            style={{
              marginTop: 18,
              background: "#ffffff",
              border: "1px solid #e5e7eb",
              borderRadius: 12,
              overflow: "hidden",
              scrollMarginTop: 16,
            }}
          >
            <div
              style={{
                padding: "12px 14px",
                borderBottom: "1px solid #e5e7eb",
                fontWeight: 600,
              }}
            >
              {formatTableName(section)}
              {section.source && (
                <InfoTooltip text={`Source: ${section.source}`} size={14} />
              )}
            </div>
            {section.description && (
              <div
                style={{
                  padding: "10px 14px",
                  color: "#6b7280",
                  fontSize: 14,
                }}
              >
                {section.description}
              </div>
            )}
            {expandedSections.has(section.tableName) &&
              section.rows.length > 5 && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "flex-end",
                    padding: "6px 14px",
                    background: "#f9fafb",
                    borderBottom: "1px solid #e5e7eb",
                  }}
                >
                  <button
                    onClick={() => toggleSection(section.tableName)}
                    style={{
                      padding: "6px 12px",
                      background: "#ffffff",
                      border: "1px solid #d1d5db",
                      color: "#1f2937",
                      borderRadius: 10,
                      fontSize: 13,
                      fontWeight: 500,
                      cursor: "pointer",
                    }}
                  >
                    Collapse
                  </button>
                </div>
              )}
            <DataTable
              columns={section.displayColumns}
              rows={section.rows}
              maxRows={expandedSections.has(section.tableName) ? undefined : 5}
              totalRows={section.rows.length}
              scalarColumns={section.scalarColumns}
              fieldLabels={section.fieldLabels}
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
    </div>
  );
}
