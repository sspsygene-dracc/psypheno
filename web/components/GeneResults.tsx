type TableResult = {
  tableName: string;
  displayColumns: string[];
  rows: Record<string, unknown>[];
};

export default function GeneResults({
  entrezId,
  data,
}: {
  entrezId: string | null;
  data: TableResult[];
}) {
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
      <h2 style={{ marginBottom: 12 }}>Results for Entrez {entrezId}</h2>
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
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {section.displayColumns.map((c) => (
                    <th
                      key={c}
                      style={{
                        textAlign: "left",
                        padding: "10px 12px",
                        fontWeight: 500,
                        borderBottom: "1px solid #334155",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {section.rows.map((r, i) => (
                  <tr key={i}>
                    {section.displayColumns.map((c) => (
                      <td
                        key={c}
                        style={{
                          padding: "10px 12px",
                          borderBottom: "1px solid #1f2937",
                        }}
                      >
                        {String(r[c] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
