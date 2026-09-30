import { useEffect, useMemo, useState } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

type ChangelogEntry = {
  date: string | null;
  message: string | null;
  table_name: string;
  // 1 when the entry is part of the table's addition (dated on its first
  // changelog date), 0 for a later update (#243).
  is_initial: number;
  dataset: string | null;
  short_label: string | null;
  medium_label: string | null;
  long_label: string | null;
  description: string | null;
  organism: string | null;
  source: string | null;
  publication_title: string | null;
  publication_first_author: string | null;
  publication_last_author: string | null;
  publication_author_count: number | null;
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
  const count = entry.publication_author_count;
  if (first && last) {
    if (first === last) return first;
    return count != null && count > 2 ? `${first}, ..., ${last}` : `${first} & ${last}`;
  }
  if (first) return `${first} et al.`;
  return last ?? "";
}

function slugFromLabel(label: string): string {
  return label.replace(/\s+/g, "_");
}

type View = "all" | "new" | "updates";

const VIEWS: { key: View; label: string }[] = [
  { key: "all", label: "All changes" },
  { key: "new", label: "New datasets" },
  { key: "updates", label: "Updates" },
];

const DESCRIPTIONS: Record<View, string> = {
  all: "History of additions and updates to the SSPsyGene dataset collection",
  new: "Datasets in the order they were added, newest first — one row per paper and date added",
  updates: "Changes to datasets after they were first added",
};

function parseView(raw: unknown): View {
  return raw === "new" || raw === "updates" ? raw : "all";
}

// One "New datasets" row: the tables of one paper that were added on one date.
// A paper that gains a table later shows up again on that later date.
type Addition = {
  date: string | null;
  tables: ChangelogEntry[];
  paper: ChangelogEntry;
};

function groupAdditions(entries: ChangelogEntry[]): Addition[] {
  const byKey = new Map<string, Addition>();
  for (const e of entries) {
    if (!e.is_initial) continue;
    const paperKey = e.publication_doi ?? e.dataset ?? e.table_name;
    const key = `${paperKey}|${e.date}`;
    const addition = byKey.get(key) ?? { date: e.date, tables: [], paper: e };
    // A table's addition can span several same-day entries; list it once.
    if (!addition.tables.some((t) => t.table_name === e.table_name)) {
      addition.tables.push(e);
    }
    byKey.set(key, addition);
  }
  // Entries arrive newest first, and Map keeps insertion order.
  return [...byKey.values()];
}

export default function DatasetChangelog() {
  const router = useRouter();
  const view = parseView(router.query.view);
  const setView = (next: View) => {
    router.replace(
      { pathname: router.pathname, query: next === "all" ? {} : { view: next } },
      undefined,
      { shallow: true }
    );
  };
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

  const shownEntries = useMemo(
    () =>
      view === "updates" ? entries.filter((e) => !e.is_initial) : entries,
    [entries, view]
  );
  const additions = useMemo(() => groupAdditions(entries), [entries]);

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
        <title>Dataset Changelog &mdash; SSPsyGene</title>
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
          <p style={{ color: "#6b7280", marginBottom: 16 }}>
            {DESCRIPTIONS[view]}
          </p>
          <div
            role="tablist"
            aria-label="Changelog view"
            style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 20 }}
          >
            {VIEWS.map((v) => {
              const active = v.key === view;
              return (
                <button
                  key={v.key}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setView(v.key)}
                  style={{
                    padding: "6px 14px",
                    borderRadius: 9999,
                    border: `1px solid ${active ? "#2563eb" : "#d1d5db"}`,
                    background: active ? "#2563eb" : "#ffffff",
                    color: active ? "#ffffff" : "#374151",
                    fontSize: 14,
                    fontWeight: 500,
                    cursor: "pointer",
                  }}
                >
                  {v.label}
                </button>
              );
            })}
          </div>

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

          {!loading && !error && view === "new" && (
            <AdditionsTable
              additions={additions}
              thStyle={thStyle}
              tdStyle={tdStyle}
            />
          )}

          {!loading && !error && view !== "new" && (
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
                  {shownEntries.map((entry, idx) => {
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
                            href={datasetHref(entry)}
                            style={{
                              color: "#2563eb",
                              textDecoration: "none",
                              fontWeight: 500,
                            }}
                          >
                            {entry.medium_label ?? entry.short_label ?? entry.table_name}
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
                          {view === "all" && entry.is_initial ? (
                            <span style={newChipStyle}>New</span>
                          ) : null}
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
                          <PublicationCell entry={entry} />
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

const newChipStyle: React.CSSProperties = {
  display: "inline-block",
  marginRight: 6,
  padding: "1px 7px",
  borderRadius: 9999,
  background: "#dcfce7",
  color: "#166534",
  fontSize: 11,
  fontWeight: 600,
  verticalAlign: "1px",
};

function datasetHref(entry: ChangelogEntry): string {
  const slug = entry.short_label
    ? slugFromLabel(entry.short_label)
    : entry.table_name;
  return `/full-datasets?select=${encodeURIComponent(slug)}`;
}

function PublicationCell({ entry }: { entry: ChangelogEntry }) {
  const authorText = formatAuthor(entry);
  const citation = (
    <>
      {authorText}
      {entry.publication_year ? ` (${entry.publication_year})` : ""}
      {entry.publication_journal ? `, ${entry.publication_journal}` : ""}
    </>
  );
  return (
    <>
      {entry.publication_doi ? (
        <a
          href={`https://doi.org/${entry.publication_doi}`}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: "#2563eb", textDecoration: "none" }}
        >
          {citation}
        </a>
      ) : (
        citation
      )}
      {entry.publication_doi && (
        <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
          DOI: {entry.publication_doi}
        </div>
      )}
    </>
  );
}

function AdditionsTable({
  additions,
  thStyle,
  tdStyle,
}: {
  additions: Addition[];
  thStyle: React.CSSProperties;
  tdStyle: React.CSSProperties;
}) {
  if (additions.length === 0) {
    return (
      <div style={{ color: "#6b7280", textAlign: "center", marginTop: 32 }}>
        No datasets have a changelog entry yet.
      </div>
    );
  }
  return (
    <div
      style={{
        background: "#ffffff",
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        overflowX: "auto",
        overflowY: "hidden",
      }}
    >
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Added</th>
            <th style={{ ...thStyle, width: "40%" }}>Paper</th>
            <th style={{ ...thStyle, width: "36%" }}>Tables</th>
            <th style={thStyle}>Organism</th>
          </tr>
        </thead>
        <tbody>
          {additions.map((a) => (
            <tr key={`${a.paper.publication_doi ?? a.paper.table_name}-${a.date}`}>
              <td
                style={{
                  ...tdStyle,
                  whiteSpace: "nowrap",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {formatDate(a.date)}
              </td>
              <td style={{ ...tdStyle, fontSize: 13, color: "#4b5563" }}>
                {a.paper.publication_title && (
                  <div style={{ color: "#1f2937", fontWeight: 500, marginBottom: 2 }}>
                    {a.paper.publication_doi ? (
                      <Link
                        href={`/publications#pub-${encodeURIComponent(
                          a.paper.publication_doi
                        )}`}
                        style={{ color: "#1f2937", textDecoration: "none" }}
                      >
                        {a.paper.publication_title}
                      </Link>
                    ) : (
                      a.paper.publication_title
                    )}
                  </div>
                )}
                <PublicationCell entry={a.paper} />
              </td>
              <td style={tdStyle}>
                {a.tables.map((t) => (
                  <div key={t.table_name} style={{ marginBottom: 4 }}>
                    <Link
                      href={datasetHref(t)}
                      style={{
                        color: "#2563eb",
                        textDecoration: "none",
                        fontWeight: 500,
                      }}
                    >
                      {t.medium_label ?? t.short_label ?? t.table_name}
                    </Link>
                  </div>
                ))}
              </td>
              <td
                style={{
                  ...tdStyle,
                  fontSize: 13,
                  color: "#4b5563",
                }}
              >
                {[...new Set(a.tables.map((t) => t.organism ?? "—"))].join(", ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
