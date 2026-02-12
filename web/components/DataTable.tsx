import { useState, useMemo, useEffect } from "react";

function formatColumnHeader(col: string): string {
  return col
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

type SortMode = "none" | "asc" | "desc" | "asc_abs" | "desc_abs";

function sortIndicator(mode: SortMode): string {
  switch (mode) {
    case "asc": return " \u25B2";
    case "desc": return " \u25BC";
    case "asc_abs": return " |\u25B2|";
    case "desc_abs": return " |\u25BC|";
    default: return " \u21C5";
  }
}

export default function DataTable({
  columns,
  rows,
  maxRows,
  totalRows,
  showSummary = true,
  scalarColumns,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  maxRows?: number;
  totalRows?: number;
  showSummary?: boolean;
  scalarColumns?: string[];
}) {
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortMode, setSortMode] = useState<SortMode>("none");

  const scalarSet = useMemo(() => {
    console.log("[DataTable] scalarColumns prop:", scalarColumns);
    console.log("[DataTable] columns prop:", columns);
    return new Set(scalarColumns ?? []);
  }, [scalarColumns, columns]);

  // Reset sort when data changes
  useEffect(() => {
    setSortColumn(null);
    setSortMode("none");
  }, [columns, rows]);

  const handleHeaderClick = (col: string) => {
    if (sortColumn !== col) {
      setSortColumn(col);
      setSortMode("asc");
      return;
    }
    const isScalar = scalarSet.has(col);
    const cycle: SortMode[] = isScalar
      ? ["asc", "desc", "asc_abs", "desc_abs", "none"]
      : ["asc", "desc", "none"];
    const idx = cycle.indexOf(sortMode);
    const next = cycle[(idx + 1) % cycle.length];
    if (next === "none") {
      setSortColumn(null);
    }
    setSortMode(next);
  };

  const sortedRows = useMemo(() => {
    if (!sortColumn || sortMode === "none") return rows;

    const isAbsSort = sortMode === "asc_abs" || sortMode === "desc_abs";
    const isAsc = sortMode === "asc" || sortMode === "asc_abs";
    const isScalar = scalarSet.has(sortColumn);

    return [...rows].sort((a, b) => {
      const va = a[sortColumn];
      const vb = b[sortColumn];

      // Nulls always sort to end
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;

      let cmp: number;
      if (isScalar) {
        let na = Number(va);
        let nb = Number(vb);
        if (isNaN(na) && isNaN(nb)) return 0;
        if (isNaN(na)) return 1;
        if (isNaN(nb)) return -1;
        if (isAbsSort) {
          na = Math.abs(na);
          nb = Math.abs(nb);
        }
        cmp = na - nb;
      } else {
        cmp = String(va).localeCompare(String(vb));
      }

      return isAsc ? cmp : -cmp;
    });
  }, [rows, sortColumn, sortMode, scalarSet]);

  const rowsToDisplay = maxRows ? sortedRows.slice(0, maxRows) : sortedRows;

  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: 14,
        }}
      >
        <thead>
          <tr style={{ background: "#f9fafb" }}>
            {columns.map((col) => {
              const isActive = col === sortColumn && sortMode !== "none";
              return (
                <th
                  key={col}
                  onClick={() => handleHeaderClick(col)}
                  style={{
                    padding: "12px 16px",
                    textAlign: "left",
                    color: isActive ? "#1f2937" : "#6b7280",
                    fontWeight: 600,
                    borderTop: "1px solid #e5e7eb",
                    whiteSpace: "nowrap",
                    cursor: "pointer",
                    userSelect: "none",
                  }}
                >
                  {formatColumnHeader(col)}
                  <span
                    style={{
                      fontSize: isActive ? 12 : 18,
                      marginLeft: 4,
                      color: isActive ? "#1f2937" : "#9ca3af",
                    }}
                  >
                    {sortIndicator(isActive ? sortMode : "none")}
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rowsToDisplay.map((row, idx) => (
            <tr key={idx} style={{ borderTop: "1px solid #e5e7eb" }}>
              {columns.map((col) => (
                <td
                  key={col}
                  style={{
                    padding: "12px 16px",
                    color: "#1f2937",
                  }}
                >
                  {String(row[col] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {showSummary && (
        <div
          style={{
            padding: 16,
            textAlign: "center",
            color: "#6b7280",
            fontSize: 14,
            borderTop: "1px solid #e5e7eb",
          }}
        >
          {(() => {
            const shown = maxRows
              ? Math.min(rows.length, maxRows)
              : rows.length;
            const total = totalRows ?? rows.length;
            return `Showing first ${shown} of ${total} rows`;
          })()}
        </div>
      )}
    </div>
  );
}
