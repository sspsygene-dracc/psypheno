import { useEffect, useRef, useState, type ReactNode } from "react";
import Head from "next/head";
import { useRouter } from "next/router";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import DataTable, { type SortMode } from "@/components/DataTable";
import InfoTooltip from "@/components/InfoTooltip";
import DatasetItem, { Dataset } from "@/components/DatasetItem";

type DatasetData = {
  tableName: string;
  shortLabel: string | null;
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
  const [assayTypeLabels, setAssayTypeLabels] = useState<Record<string, string>>({});
  const [loadingPage, setLoadingPage] = useState(false);
  const [sortBy, setSortBy] = useState<string | null>(null);
  const [sortMode, setSortMode] = useState<SortMode>("none");
  const hydratedFromQuery = useRef(false);
  const pageAbort = useRef<AbortController | null>(null);

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
    const fetchAssayTypes = async () => {
      try {
        const res = await fetch("/api/assay-types");
        if (res.ok) {
          const data = await res.json();
          setAssayTypeLabels(data.assayTypes ?? {});
        }
      } catch {
        // Non-critical, assay keys will be shown as-is
      }
    };
    fetchDatasets();
    fetchAssayTypes();
  }, []);

  // Hydrate selected dataset from ?select= URL param once datasets are loaded
  useEffect(() => {
    if (!router.isReady || hydratedFromQuery.current || loading) return;
    hydratedFromQuery.current = true;
    const selectParam = router.query.select;
    if (typeof selectParam !== "string") return;
    const normalized = normalizeSlug(selectParam);
    const match = datasets.find(
      (d) => d.short_label && normalizeSlug(d.short_label) === normalized
    );
    if (match) {
      setSelectedDataset(match.table_name);
    }
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

  // Reset sort when dataset changes
  useEffect(() => {
    setSortBy(null);
    setSortMode("none");
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
    fetchDatasetData();
  }, [selectedDataset]);

  useEffect(() => {
    if (!loadingData && datasetData && selectedDataset) {
      const anchor = document.getElementById("dataset-table-top");
      if (anchor) {
        anchor.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  }, [loadingData, selectedDataset]);

  const buildFetchUrl = (page: number, overrideSortBy?: string | null, overrideSortMode?: SortMode) => {
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
    return `/api/dataset-data?${params.toString()}`;
  };

  const fetchPage = async (page: number, overrideSortBy?: string | null, overrideSortMode?: SortMode) => {
    if (!selectedDataset) return;
    pageAbort.current?.abort();
    const controller = new AbortController();
    pageAbort.current = controller;
    setLoadingPage(true);
    try {
      const url = buildFetchUrl(page, overrideSortBy, overrideSortMode);
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
        <title>All Datasets - SSPsyGene</title>
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
            All Datasets
          </h1>
          <p style={{ color: "#6b7280", marginBottom: 24 }}>
            Browse all available datasets in the SSPsyGene database
          </p>

          {loading && (
            <div
              style={{ color: "#6b7280", textAlign: "center", marginTop: 32 }}
            >
              Loading datasets...
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
            <div style={{ display: "grid", gap: 24 }}>
              <div
                style={{
                  background: "#ffffff",
                  border: "1px solid #e5e7eb",
                  borderRadius: 12,
                  overflowX: "auto",
                  overflowY: "hidden",
                }}
              >
                <div
                  style={{
                    padding: "16px",
                    background: "#f9fafb",
                    color: "#6b7280",
                    fontWeight: 600,
                    fontSize: 14,
                  }}
                >
                  Available Datasets ({datasets.length})
                </div>
                <div>
                  {datasets.map((dataset) => (
                    <DatasetItem
                      key={dataset.table_name}
                      dataset={dataset}
                      onSelect={setSelectedDataset}
                      assayTypeLabels={assayTypeLabels}
                    />
                  ))}
                </div>
              </div>

              {selectedDataset && (
                <>
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
                      }}
                    >
                      {datasetData?.shortLabel ??
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
                                return `Showing rows ${rangeStart.toLocaleString()}\u2013${rangeEnd.toLocaleString()} of ${total.toLocaleString()}`;
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
                </>
              )}
            </div>
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}
