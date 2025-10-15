import React from "react";

export default function DataTable({
  columns,
  rows,
  maxRows,
  totalRows,
  showSummary = true,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  maxRows?: number;
  totalRows?: number;
  showSummary?: boolean;
}) {
  const rowsToDisplay = maxRows ? rows.slice(0, maxRows) : rows;
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
          <tr style={{ background: "#1e293b" }}>
            {columns.map((col) => (
              <th
                key={col}
                style={{
                  padding: "12px 16px",
                  textAlign: "left",
                  color: "#94a3b8",
                  fontWeight: 600,
                  borderTop: "1px solid #334155",
                  whiteSpace: "nowrap",
                }}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rowsToDisplay.map((row, idx) => (
            <tr key={idx} style={{ borderTop: "1px solid #334155" }}>
              {columns.map((col) => (
                <td
                  key={col}
                  style={{
                    padding: "12px 16px",
                    color: "#e5e7eb",
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
            color: "#94a3b8",
            fontSize: 14,
            borderTop: "1px solid #334155",
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
