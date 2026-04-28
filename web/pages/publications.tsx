import { useEffect, useMemo, useState } from "react";
import Head from "next/head";
import { useRouter } from "next/router";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import DatasetItem, { type Dataset } from "@/components/DatasetItem";
import InfoTooltip from "@/components/InfoTooltip";
import { formatAuthors } from "@/lib/format-authors";
import type {
  PublicationEntry,
  PublicationTableEntry,
} from "@/pages/api/publications";

const TITLE_CASE_RE = /\w\S*/g;

function titleCase(s: string): string {
  return s.replace(TITLE_CASE_RE, (t) => t.charAt(0).toUpperCase() + t.slice(1));
}

// "Homo sapiens (organoids)" → "homo sapiens" (lowercase, paren-stripped, trimmed).
function normalizeOrganism(raw: string): string {
  return raw.replace(/\s*\(.*$/u, "").trim().toLowerCase();
}

function hostFromUrl(url: string): string {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function slugFromLabel(label: string): string {
  return label.replace(/\s+/g, "_");
}

export default function PublicationsPage() {
  const router = useRouter();
  const [publications, setPublications] = useState<PublicationEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [assayTypeLabels, setAssayTypeLabels] = useState<Record<string, string>>({});

  const [authorQuery, setAuthorQuery] = useState("");
  const [yearFilter, setYearFilter] = useState<Set<number>>(new Set());
  const [organismFilter, setOrganismFilter] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    fetch("/api/publications")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => {
        if (!cancelled) {
          setPublications(data.publications || []);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e.message || "Failed to load");
          setLoading(false);
        }
      });
    fetch("/api/assay-types")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data) setAssayTypeLabels(data.assayTypes ?? {});
      })
      .catch(() => {
        // non-critical
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Honor #pub-<doi> URL fragment after content loads.
  useEffect(() => {
    if (loading) return;
    if (typeof window === "undefined") return;
    const hash = window.location.hash;
    if (!hash) return;
    const id = hash.slice(1);
    requestAnimationFrame(() => {
      const el = document.getElementById(id);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [loading]);

  // Build facet options from the data.
  const yearOptions = useMemo(() => {
    const set = new Set<number>();
    for (const p of publications) if (p.year != null) set.add(p.year);
    return Array.from(set).sort((a, b) => b - a);
  }, [publications]);

  const organismOptions = useMemo(() => {
    const counts = new Map<string, { display: string; count: number }>();
    for (const p of publications) {
      const seen = new Set<string>();
      for (const o of p.organisms) {
        const key = normalizeOrganism(o);
        if (!key || seen.has(key)) continue;
        seen.add(key);
        const prev = counts.get(key);
        if (prev) prev.count += 1;
        else counts.set(key, { display: titleCase(key), count: 1 });
      }
    }
    return Array.from(counts.entries())
      .map(([key, { display, count }]) => ({ key, display, count }))
      .sort((a, b) => a.display.localeCompare(b.display));
  }, [publications]);

  const filtered = useMemo(() => {
    const q = authorQuery.trim().toLowerCase();
    return publications.filter((p) => {
      if (q) {
        const matched = p.authors.some((a) => a.toLowerCase().includes(q));
        if (!matched) return false;
      }
      if (yearFilter.size > 0 && (p.year == null || !yearFilter.has(p.year))) {
        return false;
      }
      if (organismFilter.size > 0) {
        const orgKeys = new Set(p.organisms.map(normalizeOrganism));
        let any = false;
        for (const k of organismFilter) {
          if (orgKeys.has(k)) {
            any = true;
            break;
          }
        }
        if (!any) return false;
      }
      return true;
    });
  }, [publications, authorQuery, yearFilter, organismFilter]);

  const toggleYear = (y: number) => {
    setYearFilter((prev) => {
      const next = new Set(prev);
      if (next.has(y)) next.delete(y);
      else next.add(y);
      return next;
    });
  };
  const toggleOrganism = (key: string) => {
    setOrganismFilter((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const goToDataset = (dataset: Dataset) => {
    const slug = dataset.short_label
      ? slugFromLabel(dataset.short_label)
      : dataset.table_name;
    router.push(`/all-datasets?open=${encodeURIComponent(slug)}`);
  };

  return (
    <>
      <Head>
        <title>Publications &amp; Datasets &mdash; SSPsyGene</title>
      </Head>
      <Header />
      <main
        style={{
          maxWidth: 1200,
          margin: "0 auto",
          padding: "24px 16px",
          color: "#1f2937",
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>
          Publications &amp; Datasets
        </h1>
        <p
          style={{
            color: "#4b5563",
            fontSize: 15,
            lineHeight: 1.6,
            marginBottom: 20,
          }}
        >
          Papers contributing data to the SSPsyGene knowledge base, with their
          source datasets shown beneath each publication. Filter by author,
          publication year, or experimental organism. Click a dataset to expand
          its metadata, or jump straight to its full data table.
        </p>

        <style>{`
          .pubs-layout {
            display: grid;
            grid-template-columns: 240px 1fr;
            gap: 24px;
            align-items: flex-start;
          }
          @media (max-width: 900px) {
            .pubs-layout { grid-template-columns: 1fr; }
            .pubs-facets { position: static !important; }
          }
        `}</style>

        <div className="pubs-layout">
          <aside
            className="pubs-facets"
            style={{
              position: "sticky",
              top: 16,
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              padding: 16,
              background: "#f9fafb",
              fontSize: 13,
            }}
          >
            <div style={{ marginBottom: 16 }}>
              <label
                htmlFor="pubs-author"
                style={{ display: "block", fontWeight: 600, marginBottom: 6 }}
              >
                Author
              </label>
              <input
                id="pubs-author"
                type="search"
                value={authorQuery}
                onChange={(e) => setAuthorQuery(e.target.value)}
                placeholder="Search any author"
                style={{
                  width: "100%",
                  boxSizing: "border-box",
                  padding: "6px 8px",
                  border: "1px solid #d1d5db",
                  borderRadius: 6,
                  fontSize: 13,
                }}
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Year</div>
              {yearOptions.length === 0 ? (
                <div style={{ color: "#9ca3af" }}>—</div>
              ) : (
                yearOptions.map((y) => (
                  <label
                    key={y}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "2px 0",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={yearFilter.has(y)}
                      onChange={() => toggleYear(y)}
                    />
                    <span>{y}</span>
                  </label>
                ))
              )}
            </div>

            <div>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Organism</div>
              {organismOptions.length === 0 ? (
                <div style={{ color: "#9ca3af" }}>—</div>
              ) : (
                organismOptions.map((opt) => (
                  <label
                    key={opt.key}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "2px 0",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={organismFilter.has(opt.key)}
                      onChange={() => toggleOrganism(opt.key)}
                    />
                    <span style={{ flex: 1 }}>{opt.display}</span>
                    <span style={{ color: "#6b7280", fontSize: 12 }}>
                      {opt.count}
                    </span>
                  </label>
                ))
              )}
            </div>

            {(authorQuery || yearFilter.size > 0 || organismFilter.size > 0) && (
              <button
                type="button"
                onClick={() => {
                  setAuthorQuery("");
                  setYearFilter(new Set());
                  setOrganismFilter(new Set());
                }}
                style={{
                  marginTop: 16,
                  width: "100%",
                  padding: "6px 10px",
                  background: "#ffffff",
                  border: "1px solid #d1d5db",
                  color: "#1f2937",
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                Clear filters
              </button>
            )}
          </aside>

          <section style={{ minWidth: 0 }}>
            {loading ? (
              <div style={{ color: "#6b7280" }}>Loading publications…</div>
            ) : error ? (
              <div style={{ color: "#dc2626" }}>Failed to load: {error}</div>
            ) : filtered.length === 0 ? (
              <div style={{ color: "#6b7280", padding: "12px 0" }}>
                No publications match the current filters.
              </div>
            ) : (
              <>
                <div
                  style={{
                    color: "#6b7280",
                    fontSize: 13,
                    marginBottom: 12,
                  }}
                >
                  Showing {filtered.length} of {publications.length} publications
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                  {filtered.map((p) => (
                    <PublicationCard
                      key={p.doi}
                      pub={p}
                      assayTypeLabels={assayTypeLabels}
                      onOpenDataset={goToDataset}
                    />
                  ))}
                </div>
              </>
            )}
          </section>
        </div>
      </main>
      <Footer />
    </>
  );
}

function PublicationCard({
  pub,
  assayTypeLabels,
  onOpenDataset,
}: {
  pub: PublicationEntry;
  assayTypeLabels: Record<string, string>;
  onOpenDataset: (d: Dataset) => void;
}) {
  const citation = formatAuthors(
    pub.firstAuthor ?? undefined,
    pub.lastAuthor ?? undefined,
    pub.authorCount ?? undefined,
  );
  const distinctTableLinks = useMemo(() => {
    const seen = new Set<string>();
    const out: { url: string; tableName: string }[] = [];
    for (const t of pub.tables) {
      for (const url of t.links) {
        if (seen.has(url)) continue;
        seen.add(url);
        out.push({ url, tableName: t.tableName });
      }
    }
    return out;
  }, [pub.tables]);

  return (
    <article
      id={`pub-${encodeURIComponent(pub.doi)}`}
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        padding: "16px 18px",
        background: "#ffffff",
        scrollMarginTop: 16,
      }}
    >
      <header style={{ marginBottom: 10 }}>
        <div style={{ fontWeight: 600, fontSize: 16, color: "#1f2937" }}>
          {citation || "Unknown authors"}
          {pub.year != null && ` (${pub.year})`}
          {pub.journal && (
            <span style={{ fontWeight: 400, color: "#4b5563" }}>
              {" "}— {pub.journal}
            </span>
          )}
        </div>
        {pub.authors.length > 0 && (
          <AuthorListLine authors={pub.authors} />
        )}
        <div
          style={{
            marginTop: 4,
            fontSize: 13,
            color: "#6b7280",
            display: "flex",
            gap: 14,
            flexWrap: "wrap",
          }}
        >
          <a
            href={`https://doi.org/${pub.doi}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "#2563eb", textDecoration: "underline" }}
          >
            doi:{pub.doi}
          </a>
          {pub.pmid && (
            <a
              href={`https://pubmed.ncbi.nlm.nih.gov/${pub.pmid}/`}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: "#2563eb", textDecoration: "underline" }}
            >
              PMID:{pub.pmid}
            </a>
          )}
        </div>
      </header>

      {pub.organisms.length > 0 && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
            marginBottom: 12,
          }}
        >
          {pub.organisms.map((o) => (
            <span
              key={o}
              style={{
                fontSize: 12,
                color: "#1e40af",
                background: "#dbeafe",
                borderRadius: 9999,
                padding: "2px 10px",
              }}
            >
              {o}
            </span>
          ))}
        </div>
      )}

      <div style={{ marginBottom: distinctTableLinks.length > 0 ? 10 : 0 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "#374151",
            marginBottom: 8,
          }}
        >
          Datasets ({pub.tables.length})
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {pub.tables.map((t) => (
            <CollapsibleDatasetCard
              key={t.tableName}
              entry={t}
              assayTypeLabels={assayTypeLabels}
              onOpenDataset={onOpenDataset}
            />
          ))}
        </div>
      </div>

      {distinctTableLinks.length > 0 && (
        <div>
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: "#374151",
              marginBottom: 6,
            }}
          >
            Raw data / supplementary
          </div>
          <ul
            style={{
              margin: 0,
              paddingLeft: 18,
              color: "#1f2937",
              fontSize: 13,
            }}
          >
            {distinctTableLinks.map(({ url }) => (
              <li key={url}>
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "#2563eb", textDecoration: "underline" }}
                >
                  {hostFromUrl(url)}
                </a>{" "}
                <span style={{ color: "#9ca3af", fontSize: 12 }}>
                  — {url}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

const AUTHOR_LINE_COLLAPSED_LIMIT = 8;

function AuthorListLine({ authors }: { authors: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const overflow = authors.length > AUTHOR_LINE_COLLAPSED_LIMIT;
  const visible =
    expanded || !overflow ? authors : authors.slice(0, AUTHOR_LINE_COLLAPSED_LIMIT);
  const hidden = overflow && !expanded ? authors.length - visible.length : 0;
  return (
    <div
      style={{
        marginTop: 3,
        fontSize: 13,
        color: "#9ca3af",
        lineHeight: 1.5,
      }}
    >
      {visible.join(", ")}
      {hidden > 0 && (
        <>
          {", "}
          <button
            type="button"
            onClick={() => setExpanded(true)}
            style={{
              background: "transparent",
              border: "none",
              color: "#6b7280",
              cursor: "pointer",
              padding: 0,
              fontSize: 13,
              textDecoration: "underline",
            }}
          >
            +{hidden} more
          </button>
        </>
      )}
      {expanded && overflow && (
        <>
          {" · "}
          <button
            type="button"
            onClick={() => setExpanded(false)}
            style={{
              background: "transparent",
              border: "none",
              color: "#6b7280",
              cursor: "pointer",
              padding: 0,
              fontSize: 13,
              textDecoration: "underline",
            }}
          >
            show fewer
          </button>
        </>
      )}
    </div>
  );
}

function CollapsibleDatasetCard({
  entry,
  assayTypeLabels,
  onOpenDataset,
}: {
  entry: PublicationTableEntry;
  assayTypeLabels: Record<string, string>;
  onOpenDataset: (d: Dataset) => void;
}) {
  const [open, setOpen] = useState(false);
  const ds = entry.dataset;
  const colCount = (ds.display_columns || "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean).length;
  const assays = (ds.assay || "")
    .split(",")
    .map((a) => a.trim())
    .filter(Boolean);

  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        background: "#ffffff",
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          width: "100%",
          padding: "10px 12px",
          background: open ? "#f3f4f6" : "#fafafa",
          border: "none",
          borderBottom: open ? "1px solid #e5e7eb" : "none",
          textAlign: "left",
          cursor: "pointer",
          fontFamily: "inherit",
          color: "inherit",
        }}
      >
        <span
          aria-hidden
          style={{
            display: "inline-block",
            transform: open ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 0.15s ease",
            color: "#6b7280",
            fontSize: 12,
            width: 12,
          }}
        >
          ▶
        </span>
        <span style={{ flex: 1, minWidth: 0 }}>
          <span
            style={{
              fontWeight: 600,
              fontSize: 15,
              color: "#111827",
              display: "block",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {entry.label}
            {ds.source && (
              <InfoTooltip text={`Source: ${ds.source}`} size={13} />
            )}
          </span>
          <span
            style={{
              fontSize: 12,
              color: "#6b7280",
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
              marginTop: 2,
            }}
          >
            {entry.organism && <span>{entry.organism}</span>}
            {assays.length > 0 && (
              <span>{assays.map((a) => assayTypeLabels[a] ?? a).join(", ")}</span>
            )}
            <span>{colCount} columns</span>
          </span>
        </span>
      </button>
      {open && (
        <div style={{ background: "#ffffff" }}>
          <DatasetItem
            dataset={ds}
            onSelect={() => onOpenDataset(ds)}
            assayTypeLabels={assayTypeLabels}
            compact
          />
        </div>
      )}
    </div>
  );
}
