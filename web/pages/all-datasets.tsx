import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import DataTable, { type SortMode } from "@/components/DataTable";
import InfoTooltip from "@/components/InfoTooltip";
import type { Dataset } from "@/components/DatasetItem";

type DatasetData = {
  tableName: string;
  shortLabel: string | null;
  mediumLabel: string | null;
  longLabel: string | null;
  description: string | null;
  organism: string | null;
  source: string | null;
  links: string[];
  categories: string[];
  assay: string[];
  fieldLabels: Record<string, string> | null;
  publication: {
    firstAuthor: string | null;
    lastAuthor: string | null;
    year: number | null;
    journal: string | null;
    doi: string | null;
    pmid: string | null;
  } | null;
  displayColumns: string[];
  scalarColumns?: string[];
  rows: Record<string, unknown>[];
  totalRows?: number;
  page?: number;
  totalPages?: number;
};

function slugFromLabel(label: string): string {
  return label.replace(/\s+/g, "_");
}

function normalizeSlug(s: string): string {
  return s.replace(/[\s_]+/g, "_").toLowerCase();
}

export default function AllDatasets() {
  const router = useRouter();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [datasetData, setDatasetData] = useState<DatasetData | null>(null);
  const [loadingData, setLoadingData] = useState(false);
  const [loadingPage, setLoadingPage] = useState(false);
  const [sortBy, setSortBy] = useState<string | null>(null);
  const [sortMode, setSortMode] = useState<SortMode>("none");
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({});
  const hydratedFromQuery = useRef(false);
  const pageAbort = useRef<AbortController | null>(null);
  const filterDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const fetchDatasets = async () => {
      try {
        const res = await fetch("/api/all-datasets");
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const data = await res.json();
        setDatasets(data.datasets);
      } catch (e: any) {
        setError(e?.message || "Failed to load datasets");
      } finally {
        setLoading(false);
      }
    };
    fetchDatasets();
  }, []);

  // Hydrate selected dataset from ?select= or ?open= URL param once datasets
  // are loaded. Both params now have the same effect: select the dataset and
  // show its full data table.
  useEffect(() => {
    if (!router.isReady || hydratedFromQuery.current || loading) return;
    hydratedFromQuery.current = true;
    const openParam = router.query.open;
    const selectParam = router.query.select;
    const param =
      typeof openParam === "string"
        ? openParam
        : typeof selectParam === "string"
          ? selectParam
          : null;
    if (param === null) return;
    const normalized = normalizeSlug(param);
    const match = datasets.find(
      (d) =>
        (d.short_label && normalizeSlug(d.short_label) === normalized) ||
        normalizeSlug(d.table_name) === normalized
    );
    if (match) setSelectedDataset(match.table_name);
  }, [router.isReady, loading, datasets]);

  // Keep URL in sync when the user selects a dataset
  useEffect(() => {
    if (!router.isReady || !hydratedFromQuery.current) return;
    const ds = datasets.find((d) => d.table_name === selectedDataset);
    const slug = ds?.short_label ? slugFromLabel(ds.short_label) : null;
    const currentSelect = router.query.select as string | undefined;
    if (slug) {
      if (currentSelect !== slug) {
        router.replace(
          { pathname: router.pathname, query: { select: slug } },
          undefined,
          { shallow: true }
        );
      }
    } else if (currentSelect) {
      router.replace(
        { pathname: router.pathname, query: {} },
        undefined,
        { shallow: true }
      );
    }
  }, [selectedDataset, datasets, router.isReady]);

  // Reset sort + filters when dataset changes
  useEffect(() => {
    setSortBy(null);
    setSortMode("none");
    setColumnFilters({});
  }, [selectedDataset]);

  useEffect(() => {
    if (!selectedDataset) {
      setDatasetData(null);
      return;
    }

    const fetchDatasetData = async () => {
      setLoadingData(true);
      try {
        const res = await fetch(
          `/api/dataset-data?tableName=${encodeURIComponent(selectedDataset)}`
        );
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const data = await res.json();
        setDatasetData(data);
      } catch (e: any) {
        setError(e?.message || "Failed to load dataset data");
      } finally {
        setLoadingData(false);
      }
    };
    fetchDatasetData().then(() => {
      requestAnimationFrame(() => {
        document
          .getElementById("dataset-table-top")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }, [selectedDataset]);


  const buildFetchUrl = (
    page: number,
    overrideSortBy?: string | null,
    overrideSortMode?: SortMode,
    overrideFilters?: Record<string, string>,
  ) => {
    if (!selectedDataset) return "";
    const params = new URLSearchParams();
    params.set("tableName", selectedDataset);
    params.set("page", String(page));
    const sb = overrideSortBy !== undefined ? overrideSortBy : sortBy;
    const sm = overrideSortMode !== undefined ? overrideSortMode : sortMode;
    if (sb && sm && sm !== "none") {
      params.set("sortBy", sb);
      params.set("sortMode", sm);
    }
    const f = overrideFilters !== undefined ? overrideFilters : columnFilters;
    const active: Record<string, string> = {};
    for (const [k, v] of Object.entries(f)) {
      if (v && v.trim()) active[k] = v;
    }
    if (Object.keys(active).length > 0) {
      params.set("filters", JSON.stringify(active));
    }
    return `/api/dataset-data?${params.toString()}`;
  };

  const fetchPage = async (
    page: number,
    overrideSortBy?: string | null,
    overrideSortMode?: SortMode,
    overrideFilters?: Record<string, string>,
  ) => {
    if (!selectedDataset) return;
    pageAbort.current?.abort();
    const controller = new AbortController();
    pageAbort.current = controller;
    setLoadingPage(true);
    try {
      const url = buildFetchUrl(page, overrideSortBy, overrideSortMode, overrideFilters);
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      const data = await res.json();
      setDatasetData(data);
    } catch (e: any) {
      if (e.name === "AbortError") return;
      setError(e?.message || "Failed to load page");
    } finally {
      setLoadingPage(false);
    }
  };

  const handleSort = (col: string, mode: SortMode) => {
    const newSortBy = mode === "none" ? null : col;
    setSortBy(newSortBy);
    setSortMode(mode);
    fetchPage(1, newSortBy, mode);
  };

  const handleColumnFilterChange = (col: string, value: string) => {
    setColumnFilters((prev) => {
      const next = { ...prev };
      if (value) next[col] = value;
      else delete next[col];
      if (filterDebounce.current) clearTimeout(filterDebounce.current);
      filterDebounce.current = setTimeout(() => {
        fetchPage(1, undefined, undefined, next);
      }, 300);
      return next;
    });
  };

  const currentPage = datasetData?.page ?? 1;
  const totalPages = datasetData?.totalPages ?? 1;
  const hasPagination = totalPages > 1;
  const isPageBusy = loadingData || loadingPage;

  const renderPageNumbers = (): ReactNode => {
    if (totalPages <= 1) return null;
    const items: ReactNode[] = [];

    const addBtn = (label: string | number, targetPage: number, key: string) => {
      const isActive = targetPage === currentPage;
      const isDisabled = isPageBusy || targetPage < 1 || targetPage > totalPages;
      items.push(
        <button
          key={key}
          onClick={() => !isDisabled && !isActive && fetchPage(targetPage)}
          disabled={isDisabled}
          aria-current={isActive ? "page" : undefined}
          style={{
            padding: "4px 8px",
            minWidth: 30,
            background: isActive ? "#e5e7eb" : isDisabled ? "#f9fafb" : "#ffffff",
            border: "1px solid #d1d5db",
            color: "#1f2937",
            borderRadius: 6,
            cursor: isDisabled || isActive ? "default" : "pointer",
            fontWeight: isActive ? 700 : 500,
            fontSize: 13,
          }}
        >
          {label}
        </button>
      );
    };

    addBtn(1, 1, "pg-1");
    if (totalPages >= 2) addBtn(2, 2, "pg-2");

    const surround: number[] = [];
    for (let p = currentPage - 2; p <= currentPage + 2; p++) {
      if (p >= 1 && p <= totalPages && p !== 1 && p !== 2 && p !== totalPages) {
        surround.push(p);
      }
    }

    if (surround.length > 0 && Math.min(...surround) > 3) {
      items.push(
        <span key="pg-ell-1" style={{ color: "#6b7280", padding: "0 2px", fontSize: 13 }}>...</span>
      );
    }
    surround.forEach((pnum) => addBtn(pnum, pnum, `pg-${pnum}`));
    if (surround.length > 0 && Math.max(...surround) < totalPages - 1) {
      items.push(
        <span key="pg-ell-2" style={{ color: "#6b7280", padding: "0 2px", fontSize: 13 }}>...</span>
      );
    }
    if (totalPages > 2) addBtn(totalPages, totalPages, "pg-last");

    return (
      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>{items}</div>
    );
  };

  const pageBtnStyle = (disabled: boolean) => ({
    padding: "4px 10px",
    background: disabled ? "#f9fafb" : "#ffffff",
    border: "1px solid #d1d5db",
    color: disabled ? "#9ca3af" : "#1f2937",
    borderRadius: 6,
    cursor: disabled ? "not-allowed" : "pointer" as const,
    fontSize: 13,
    fontWeight: 500 as const,
  });

  return (
    <>
      <Head>
        <title>Full datasets &mdash; SSPsyGene</title>
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
            Full datasets
          </h1>
          <p style={{ color: "#4b5563", marginBottom: 20, lineHeight: 1.5 }}>
            Pick a dataset to view its full row-level data with sorting,
            filtering, and pagination. To browse datasets grouped by source
            paper with summaries, descriptions, and column metadata, see the{" "}
            <Link
              href="/publications"
              style={{ color: "#2563eb", textDecoration: "underline" }}
            >
              Publications page
            </Link>
            .
          </p>

          {loading && (
            <div style={{ color: "#6b7280", marginTop: 16 }}>
              Loading datasets...
            </div>
          )}

          {error && (
            <div style={{ color: "#dc2626", marginTop: 16 }}>{error}</div>
          )}

          {!loading && !error && (
            <DatasetPicker
              datasets={datasets}
              selectedTableName={selectedDataset}
              onSelect={setSelectedDataset}
            />
          )}

          {!loading && !error && selectedDataset && (
            <div style={{ marginTop: 24 }}>
              <div id="dataset-table-top" />
              <div
                style={{
                  background: "#ffffff",
                  border: "1px solid #e5e7eb",
                  borderRadius: 12,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    padding: "16px",
                    background: "#f9fafb",
                    color: "#1f2937",
                    fontWeight: 600,
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 12,
                    flexWrap: "wrap",
                  }}
                >
                  <div>
                    {datasetData?.mediumLabel ?? datasetData?.shortLabel ??
                      selectedDataset
                        ?.replace(/_/g, " ")
                        .replace(
                          /\w\S*/g,
                          (txt) => txt.charAt(0).toUpperCase() + txt.slice(1)
                        )}
                    {datasetData?.source && (
                      <InfoTooltip text={`Source: ${datasetData.source}`} size={14} />
                    )}
                  </div>
                  {datasetData?.publication?.doi && (
                    <Link
                      href={`/publications#pub-${encodeURIComponent(
                        datasetData.publication.doi,
                      )}`}
                      style={{
                        fontSize: 13,
                        fontWeight: 500,
                        color: "#2563eb",
                        textDecoration: "underline",
                      }}
                    >
                      See on Publications page
                    </Link>
                  )}
                </div>

                {loadingData && !loadingPage && (
                  <div
                    style={{
                      padding: 32,
                      textAlign: "center",
                      color: "#6b7280",
                    }}
                  >
                    Loading data...
                  </div>
                )}

                {datasetData && (
                  <>
                    <div style={{
                      opacity: loadingPage ? 0.5 : 1,
                      pointerEvents: loadingPage ? "none" : "auto",
                      position: "relative",
                      transition: "opacity 0.15s",
                    }}>
                      <DataTable
                        columns={datasetData.displayColumns}
                        rows={datasetData.rows}
                        scalarColumns={datasetData.scalarColumns}
                        fieldLabels={datasetData.fieldLabels}
                        showSummary={false}
                        sortColumn={sortBy}
                        sortMode={sortMode}
                        onSort={handleSort}
                        columnFilters={columnFilters}
                        onColumnFilterChange={handleColumnFilterChange}
                      />
                      {loadingPage && (
                        <div style={{
                          position: "absolute",
                          top: "50%",
                          left: "50%",
                          transform: "translate(-50%, -50%)",
                          fontSize: 14,
                          color: "#6b7280",
                        }}>
                          Loading...
                        </div>
                      )}
                    </div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "10px 14px",
                        borderTop: "1px solid #e5e7eb",
                        background: "#f9fafb",
                        flexWrap: "wrap",
                        gap: 8,
                      }}
                    >
                      <div style={{ opacity: 0.8, fontSize: 13 }}>
                        {(() => {
                          const total = datasetData.totalRows ?? datasetData.rows.length;
                          if (hasPagination) {
                            const pageSize = Math.ceil(total / totalPages);
                            const rangeStart = (currentPage - 1) * pageSize + 1;
                            const rangeEnd = rangeStart + datasetData.rows.length - 1;
                            return `Showing rows ${rangeStart.toLocaleString()}–${rangeEnd.toLocaleString()} of ${total.toLocaleString()}`;
                          }
                          return `Showing all ${total.toLocaleString()} rows`;
                        })()}
                      </div>
                      {hasPagination && (
                        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                          <button
                            disabled={currentPage <= 1 || isPageBusy}
                            onClick={() => fetchPage(currentPage - 1)}
                            style={pageBtnStyle(currentPage <= 1 || isPageBusy)}
                          >
                            Prev
                          </button>
                          {renderPageNumbers()}
                          <button
                            disabled={currentPage >= totalPages || isPageBusy}
                            onClick={() => fetchPage(currentPage + 1)}
                            style={pageBtnStyle(currentPage >= totalPages || isPageBusy)}
                          >
                            Next
                          </button>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}

function datasetLabel(d: Dataset): string {
  return d.medium_label ?? d.short_label ?? d.table_name;
}

function DatasetPicker({
  datasets,
  selectedTableName,
  onSelect,
}: {
  datasets: Dataset[];
  selectedTableName: string | null;
  onSelect: (tableName: string | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const selected = useMemo(
    () => datasets.find((d) => d.table_name === selectedTableName) ?? null,
    [datasets, selectedTableName],
  );

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const sorted = [...datasets].sort((a, b) =>
      datasetLabel(a).localeCompare(datasetLabel(b)),
    );
    if (!q) return sorted;
    return sorted.filter((d) => {
      const haystack = [
        d.medium_label ?? "",
        d.short_label ?? "",
        d.long_label ?? "",
        d.table_name,
        d.organism ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [datasets, query]);

  useEffect(() => {
    if (highlight >= matches.length) setHighlight(0);
  }, [matches.length, highlight]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const pick = (d: Dataset) => {
    onSelect(d.table_name);
    setOpen(false);
    setQuery("");
    inputRef.current?.blur();
  };

  const onKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setHighlight((h) => Math.min(h + 1, matches.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const m = matches[highlight];
      if (m) pick(m);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={containerRef} style={{ position: "relative", maxWidth: 640 }}>
      <label
        htmlFor="dataset-search"
        style={{
          display: "block",
          fontSize: 13,
          fontWeight: 600,
          color: "#374151",
          marginBottom: 6,
        }}
      >
        Find a dataset
      </label>
      <div style={{ position: "relative" }}>
        <input
          ref={inputRef}
          id="dataset-search"
          type="search"
          autoComplete="off"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setHighlight(0);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={
            selected
              ? `Currently showing: ${datasetLabel(selected)}`
              : `Search ${datasets.length} datasets by name, organism, or description…`
          }
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "10px 12px",
            border: "1px solid #d1d5db",
            borderRadius: 8,
            fontSize: 14,
            background: "#ffffff",
            color: "#1f2937",
          }}
        />
        {selected && (
          <button
            type="button"
            onClick={() => onSelect(null)}
            aria-label="Clear selected dataset"
            style={{
              position: "absolute",
              right: 8,
              top: "50%",
              transform: "translateY(-50%)",
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: "#6b7280",
              fontSize: 18,
              lineHeight: 1,
              padding: "4px 8px",
            }}
          >
            ×
          </button>
        )}
      </div>

      {open && matches.length > 0 && (
        <div
          role="listbox"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            zIndex: 50,
            background: "#ffffff",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
            maxHeight: 360,
            overflowY: "auto",
          }}
        >
          {matches.map((d, i) => {
            const isHighlighted = i === highlight;
            const isSelected = d.table_name === selectedTableName;
            return (
              <button
                key={d.table_name}
                type="button"
                role="option"
                aria-selected={isSelected}
                onMouseEnter={() => setHighlight(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(d);
                }}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: "8px 12px",
                  background: isHighlighted ? "#f3f4f6" : "transparent",
                  border: "none",
                  borderBottom: "1px solid #f3f4f6",
                  cursor: "pointer",
                  fontFamily: "inherit",
                  color: "inherit",
                }}
              >
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 600,
                    color: "#111827",
                    display: "flex",
                    gap: 6,
                    alignItems: "baseline",
                  }}
                >
                  <span>{datasetLabel(d)}</span>
                  {isSelected && (
                    <span style={{ fontSize: 11, color: "#2563eb" }}>
                      • selected
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
                  {d.organism ?? d.gene_species}
                  {d.assay && ` · ${d.assay}`}
                </div>
              </button>
            );
          })}
        </div>
      )}
      {open && matches.length === 0 && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            zIndex: 50,
            background: "#ffffff",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            padding: "10px 12px",
            color: "#6b7280",
            fontSize: 13,
          }}
        >
          No matching datasets.
        </div>
      )}
    </div>
  );
}
