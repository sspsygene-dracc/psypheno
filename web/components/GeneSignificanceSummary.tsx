import { useState } from "react";

export type CombinedPvalues = {
  fisher: number | null;
  fisherFdr: number | null;
  cauchy: number | null;
  cauchyFdr: number | null;
  hmp: number | null;
  hmpFdr: number | null;
  numTables: number;
  numPvalues: number;
};

export type ContributingTable = {
  tableName: string;
  shortLabel: string | null;
  mediumLabel: string | null;
  longLabel: string | null;
  description: string | null;
  bestPvalue: number | null;
  bestFdr: number | null;
  rowCount: number;
  assay: string[] | null;
};

function formatPvalue(p: number | null): string {
  if (p == null) return "—";
  if (p < 1e-300) return "< 1e-300";
  if (p < 0.001) return p.toExponential(2);
  return p.toPrecision(3);
}

const formatTableName = (tableName: string, mediumLabel: string | null) =>
  mediumLabel ??
  tableName
    .replace(/_/g, " ")
    .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1));

export default function GeneSignificanceSummary({
  combinedPvalues,
  contributingTables,
  assayTypeLabels = {},
}: {
  combinedPvalues: CombinedPvalues | null;
  contributingTables: ContributingTable[];
  assayTypeLabels?: Record<string, string>;
}) {
  const [expanded, setExpanded] = useState(true);

  if (!combinedPvalues) return null;

  const cp = combinedPvalues;
  const tables = [...contributingTables].sort((a, b) => {
    const pa = a.bestPvalue ?? 1;
    const pb = b.bestPvalue ?? 1;
    return pa - pb;
  });

  const tdStyle: React.CSSProperties = {
    padding: "4px 10px",
    whiteSpace: "nowrap",
    fontSize: 13,
  };
  const thStyle: React.CSSProperties = {
    ...tdStyle,
    fontWeight: 600,
    textAlign: "left",
    borderBottom: "1px solid #e5e7eb",
  };
  // Dataset/Assay names can be long; let them wrap with a max width so the
  // summary box doesn't extend beyond its container (especially on mobile).
  const wrapTdStyle: React.CSSProperties = {
    ...tdStyle,
    whiteSpace: "normal",
    overflowWrap: "anywhere",
  };
  const wrapThStyle: React.CSSProperties = {
    ...thStyle,
    whiteSpace: "normal",
    overflowWrap: "anywhere",
  };

  return (
    <div
      className="gene-sig-summary"
      style={{
        marginTop: 16,
        marginBottom: 16,
        border: "1px solid #dbeafe",
        borderRadius: 8,
        background: "#f8fafc",
        overflow: "hidden",
      }}
    >
      <style>{`
        .gene-sig-summary table { table-layout: auto; }
        .gene-sig-summary .col-dataset { max-width: 280px; }
        .gene-sig-summary .col-assay { max-width: 160px; }
        .gene-sig-summary tbody tr:nth-child(even) { background: #eef2f7; }
        .gene-sig-summary tbody tr:nth-child(odd) { background: #ffffff; }
        @media (max-width: 700px) {
          .gene-sig-summary .col-dataset { max-width: 160px; }
          .gene-sig-summary .col-assay { max-width: 100px; }
        }
      `}</style>
      <button
        onClick={() => setExpanded((prev) => !prev)}
        style={{
          width: "100%",
          padding: "10px 14px",
          background: "none",
          border: "none",
          cursor: "pointer",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 14,
          fontWeight: 600,
          color: "#1e40af",
        }}
      >
        <span>
          Significance Summary — {cp.numTables} dataset
          {cp.numTables !== 1 ? "s" : ""}, {cp.numPvalues} p-value
          {cp.numPvalues !== 1 ? "s" : ""}
        </span>
        <span style={{ fontSize: 12, color: "#6b7280" }}>
          {expanded ? "▲ Hide" : "▼ Show"}
        </span>
      </button>

      {expanded && (
        <div style={{ padding: "0 14px 14px" }}>
          {/* Per-dataset breakdown */}
          {tables.length > 0 && (
            <div>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: "#6b7280",
                  marginBottom: 4,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}
              >
                Per-dataset breakdown
              </div>
              <table
                style={{
                  borderCollapse: "collapse",
                  fontSize: 13,
                  width: "100%",
                }}
              >
                <thead>
                  <tr>
                    <th className="col-dataset" style={wrapThStyle}>Dataset</th>
                    <th className="col-assay" style={wrapThStyle}>Assay</th>
                    <th style={thStyle}>Best p-value</th>
                    <th style={thStyle}>Best FDR</th>
                    <th style={{ ...thStyle, textAlign: "right" }}>Rows</th>
                  </tr>
                </thead>
                <tbody>
                  {tables.map((t) => (
                    <tr key={t.tableName}>
                      <td className="col-dataset" style={wrapTdStyle}>
                        {formatTableName(t.tableName, t.mediumLabel)}
                      </td>
                      <td className="col-assay" style={wrapTdStyle}>
                        {t.assay
                          ? t.assay
                              .map((a) => assayTypeLabels[a] || a)
                              .join(", ")
                          : "—"}
                      </td>
                      <td style={tdStyle}>{formatPvalue(t.bestPvalue)}</td>
                      <td style={tdStyle}>{formatPvalue(t.bestFdr)}</td>
                      <td style={{ ...tdStyle, textAlign: "right" }}>
                        {t.rowCount}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
