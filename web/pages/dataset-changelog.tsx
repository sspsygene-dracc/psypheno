import { useEffect, useState } from "react";
import Head from "next/head";
import Link from "next/link";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

type ChangelogEntry = {
  date: string | null;
  message: string | null;
  table_name: string;
  short_label: string | null;
  long_label: string | null;
  description: string | null;
  organism: string | null;
  source: string | null;
  publication_first_author: string | null;
  publication_last_author: string | null;
  publication_year: number | null;
  publication_journal: string | null;
  publication_doi: string | null;
};

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "Unknown";
  const date = new Date(dateStr + "T00:00:00");
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatAuthor(entry: ChangelogEntry): string {
  const first = entry.publication_first_author;
  const last = entry.publication_last_author;
  if (!first && !last) return "";
  if (first && last) {
    if (first === last) return first;
    return `${first}, ..., ${last}`;
  }
  if (first) return `${first} et al.`;
  return last ?? "";
}

function slugFromLabel(label: string): string {
  return label.replace(/\s+/g, "_");
}

export default function DatasetChangelog() {
  const [entries, setEntries] = useState<ChangelogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchEntries = async () => {
      try {
        const res = await fetch("/api/dataset-changelog");
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const data = await res.json();
        setEntries(data.entries);
      } catch (e: any) {
        setError(e?.message || "Failed to load changelog");
      } finally {
        setLoading(false);
      }
    };
    fetchEntries();
  }, []);

  const thStyle: React.CSSProperties = {
    padding: "10px 14px",
    textAlign: "left",
    fontWeight: 600,
    fontSize: 14,
    color: "#6b7280",
    background: "#f9fafb",
    borderBottom: "2px solid #e5e7eb",
    whiteSpace: "nowrap",
  };

  const tdStyle: React.CSSProperties = {
    padding: "10px 14px",
    fontSize: 14,
    color: "#1f2937",
    borderBottom: "1px solid #e5e7eb",
    verticalAlign: "top",
  };

  return (
    <>
      <Head>
        <title>Dataset Changelog - SSPsyGene</title>
      </Head>
      <div
        style={{
          minHeight: "100vh",
          background: "#ffffff",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <Header />
        <main
          style={{
            maxWidth: "1200px",
            width: "100%",
            margin: "0 auto",
            padding: "32px 16px",
            flex: 1,
          }}
        >
          <h1
            style={{
              color: "#1f2937",
              fontSize: 32,
              fontWeight: 700,
              marginBottom: 8,
            }}
          >
            Dataset Changelog
          </h1>
          <p style={{ color: "#6b7280", marginBottom: 24 }}>
            History of additions and updates to the SSPsyGene dataset collection
          </p>

          {loading && (
            <div
              style={{ color: "#6b7280", textAlign: "center", marginTop: 32 }}
            >
              Loading changelog...
            </div>
          )}

          {error && (
            <div
              style={{ color: "#dc2626", textAlign: "center", marginTop: 32 }}
            >
              {error}
            </div>
          )}

          {!loading && !error && (
            <div
              style={{
                background: "#ffffff",
                border: "1px solid #e5e7eb",
                borderRadius: 12,
                overflowX: "auto",
                overflowY: "hidden",
              }}
            >
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                }}
              >
                <thead>
                  <tr>
                    <th style={thStyle}>Date</th>
                    <th style={thStyle}>Table</th>
                    <th style={thStyle}>Change</th>
                    <th style={thStyle}>Organism</th>
                    <th style={thStyle}>Publication</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry, idx) => {
                    const authorText = formatAuthor(entry);
                    const slug = entry.short_label
                      ? slugFromLabel(entry.short_label)
                      : entry.table_name;
                    return (
                      <tr
                        key={`${entry.table_name}-${entry.date}-${idx}`}
                        style={{ transition: "background 0.15s ease" }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLTableRowElement).style.background =
                            "#f3f4f6";
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLTableRowElement).style.background =
                            "transparent";
                        }}
                      >
                        <td
                          style={{
                            ...tdStyle,
                            whiteSpace: "nowrap",
                            fontVariantNumeric: "tabular-nums",
                          }}
                        >
                          {formatDate(entry.date)}
                        </td>
                        <td style={tdStyle}>
                          <Link
                            href={`/all-datasets?select=${encodeURIComponent(slug)}`}
                            style={{
                              color: "#2563eb",
                              textDecoration: "none",
                              fontWeight: 500,
                            }}
                          >
                            {entry.short_label ?? entry.table_name}
                          </Link>
                          {entry.long_label && (
                            <div
                              style={{
                                fontSize: 13,
                                color: "#6b7280",
                                marginTop: 2,
                              }}
                            >
                              {entry.long_label}
                            </div>
                          )}
                        </td>
                        <td
                          style={{
                            ...tdStyle,
                            fontSize: 13,
                            color: "#4b5563",
                          }}
                        >
                          {entry.message ?? "—"}
                        </td>
                        <td
                          style={{
                            ...tdStyle,
                            fontSize: 13,
                            color: "#4b5563",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {entry.organism ?? "—"}
                        </td>
                        <td style={{ ...tdStyle, fontSize: 13, color: "#4b5563" }}>
                          {entry.publication_doi ? (
                            <a
                              href={`https://doi.org/${entry.publication_doi}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{ color: "#2563eb", textDecoration: "none" }}
                            >
                              {authorText}
                              {entry.publication_year
                                ? ` (${entry.publication_year})`
                                : ""}
                              {entry.publication_journal
                                ? `, ${entry.publication_journal}`
                                : ""}
                            </a>
                          ) : (
                            <>
                              {authorText}
                              {entry.publication_year
                                ? ` (${entry.publication_year})`
                                : ""}
                              {entry.publication_journal
                                ? `, ${entry.publication_journal}`
                                : ""}
                            </>
                          )}
                          {entry.publication_doi && (
                            <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
                              DOI: {entry.publication_doi}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}
