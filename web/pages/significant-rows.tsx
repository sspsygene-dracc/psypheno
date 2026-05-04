import React, { useEffect, useState } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import DataTable from "@/components/DataTable";
import DatasetToc, { useAssayGroups } from "@/components/DatasetToc";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

const PAGE_SIZE = 10;

type Regulation = "any" | "up" | "down";

type DatasetTableMeta = {
  tableName: string;
  shortLabel: string | null;
  mediumLabel: string | null;
  longLabel: string | null;
  pvalueColumn: string | null;
  fdrColumn: string | null;
  effectColumn: string | null;
  assay: string[] | null;
  disease: string[] | null;
  organismKey: string[] | null;
};

type DatasetSigResult = {
  rows: Record<string, unknown>[];
  totalRows: number;
  displayColumns: string[];
  scalarColumns: string[];
  geneColumns: string[];
  pvalueColumn: string | null;
  fdrColumn: string | null;
  fieldLabels: Record<string, string> | null;
  page: number;
};

const formatTableName = (tableName: string, mediumLabel: string | null) =>
  mediumLabel ??
  tableName
    .replace(/_/g, " ")
    .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1));

/* --- Pagination component --- */
function Pagination({
  page,
  totalPages,
  total,
  loading,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  total: number;
  loading: boolean;
  onPageChange: (p: number) => void;
}) {
  const items: React.ReactNode[] = [];
  if (totalPages > 1) {
    const addBtn = (label: string | number, target: number, key: string) => {
      const isActive = target === page;
      const isDisabled = loading || target < 1 || target > totalPages;
      items.push(
        <button
          key={key}
          onClick={() => !isDisabled && onPageChange(target)}
          disabled={isDisabled}
          aria-current={isActive ? "page" : undefined}
          style={{
            padding: "6px 10px",
            minWidth: 36,
            background: isActive ? "#f3f4f6" : isDisabled ? "#f9fafb" : "#fff",
            border: "1px solid #d1d5db",
            color: "#1f2937",
            borderRadius: 6,
            cursor: isDisabled ? "not-allowed" : "pointer",
            fontWeight: isActive ? 700 : 500,
          }}
        >
          {label}
        </button>,
      );
    };
    addBtn(1, 1, "pg-1");
    if (totalPages >= 2) addBtn(2, 2, "pg-2");
    const surround: number[] = [];
    for (let p = page - 2; p <= page + 2; p++) {
      if (p >= 1 && p <= totalPages && p !== 1 && p !== 2 && p !== totalPages)
        surround.push(p);
    }
    if (surround.length > 0 && Math.min(...surround) > 3)
      items.push(
        <span key="ell-1" style={{ color: "#6b7280", padding: "0 4px" }}>
          ...
        </span>,
      );
    surround.forEach((pn) => addBtn(pn, pn, `pg-${pn}`));
    if (surround.length > 0 && Math.max(...surround) < totalPages - 1)
      items.push(
        <span key="ell-2" style={{ color: "#6b7280", padding: "0 4px" }}>
          ...
        </span>,
      );
    if (totalPages > 2) addBtn(totalPages, totalPages, "pg-last");
  }

  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 0",
      }}
    >
      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1 || loading}
          style={{
            padding: "8px 12px",
            background: page <= 1 || loading ? "#f9fafb" : "#fff",
            border: "1px solid #d1d5db",
            color: "#1f2937",
            borderRadius: 8,
            cursor: page <= 1 || loading ? "not-allowed" : "pointer",
          }}
        >
          Prev
        </button>
        <button
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages || loading}
          style={{
            padding: "8px 12px",
            background: page >= totalPages || loading ? "#f9fafb" : "#fff",
            border: "1px solid #d1d5db",
            color: "#1f2937",
            borderRadius: 8,
            cursor: page >= totalPages || loading ? "not-allowed" : "pointer",
          }}
        >
          Next
        </button>
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {items}
      </div>
      <div style={{ color: "#6b7280", fontSize: 13, whiteSpace: "nowrap" }}>
        Page {page} of {totalPages} ({total} genes)
      </div>
    </div>
  );
}

/* --- Per-dataset significant rows section --- */
function DatasetSection({
  meta,
  filterBy,
  sortBy,
  regulation,
}: {
  meta: DatasetTableMeta;
  filterBy: "pvalue" | "fdr";
  sortBy: "pvalue" | "fdr";
  regulation: Regulation;
}) {
  const [result, setResult] = useState<DatasetSigResult | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setPage(1);
  }, [filterBy, sortBy, regulation]);

  useEffect(() => {
    setLoading(true);
    fetch("/api/dataset-significant-rows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tableName: meta.tableName,
        page,
        pageSize: PAGE_SIZE,
        filterBy,
        sortBy,
        regulation,
      }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setResult({
          rows: data.rows,
          totalRows: data.totalRows,
          displayColumns: data.displayColumns,
          scalarColumns: data.scalarColumns,
          geneColumns: data.geneColumns ?? [],
          pvalueColumn: data.pvalueColumn ?? null,
          fdrColumn: data.fdrColumn ?? null,
          fieldLabels: data.fieldLabels,
          page: data.page,
        });
        setLoading(false);
      })
      .catch(() => {
        setResult(null);
        setLoading(false);
      });
  }, [meta.tableName, page, filterBy, sortBy, regulation]);

  if (!loading && (!result || result.totalRows === 0)) return null;

  const totalPages = result
    ? Math.max(1, Math.ceil(result.totalRows / PAGE_SIZE))
    : 1;

  return (
    <div
      style={{
        marginBottom: 16,
        background: "#ffffff",
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "12px 14px",
          borderBottom: "1px solid #e5e7eb",
          fontWeight: 600,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span>{formatTableName(meta.tableName, meta.mediumLabel)}</span>
        {result && (
          <span style={{ fontSize: 13, fontWeight: 400, color: "#6b7280" }}>
            {result.totalRows} significant row
            {result.totalRows !== 1 ? "s" : ""}
          </span>
        )}
      </div>
      {loading && (
        <div style={{ padding: 16, color: "#6b7280", fontSize: 14 }}>
          Loading...
        </div>
      )}
      {!loading && result && result.rows.length > 0 && (
        <>
          <DataTable
            columns={result.displayColumns}
            rows={result.rows}
            scalarColumns={result.scalarColumns}
            geneColumns={result.geneColumns}
            pvalueColumn={result.pvalueColumn}
            fdrColumn={result.fdrColumn}
            highlightSignificantRows={false}
            fieldLabels={result.fieldLabels ?? undefined}
            showSummary={false}
          />
          {totalPages > 1 && (
            <div
              style={{
                padding: "4px 14px 8px",
                borderTop: "1px solid #e5e7eb",
              }}
            >
              <Pagination
                page={page}
                totalPages={totalPages}
                total={result.totalRows}
                loading={loading}
                onPageChange={setPage}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* --- Main page --- */
export default function SignificantRowsPage() {
  const [sigFilterBy, setSigFilterBy] = useState<"pvalue" | "fdr">("pvalue");
  const [sigSortBy, setSigSortBy] = useState<"pvalue" | "fdr">("pvalue");
  const [datasetTables, setDatasetTables] = useState<DatasetTableMeta[]>([]);
  const [assayTypeLabels, setAssayTypeLabels] = useState<
    Record<string, string>
  >({});
  const [diseaseTypeLabels, setDiseaseTypeLabels] = useState<
    Record<string, string>
  >({});
  const [organismTypeLabels, setOrganismTypeLabels] = useState<
    Record<string, string>
  >({});
  const [assayFilter, setAssayFilter] = useState<string | null>(null);
  const [diseaseFilter, setDiseaseFilter] = useState<string | null>(null);
  const [organismFilter, setOrganismFilter] = useState<string | null>(null);
  const [regulation, setRegulation] = useState<Regulation>("any");
  const [datasetsLoading, setDatasetsLoading] = useState(true);
  const [showToc, setShowToc] = useState(false);
  const router = useRouter();

  // Initialize filters from URL query params on first load
  const [initializedFromUrl, setInitializedFromUrl] = useState(false);
  useEffect(() => {
    if (!router.isReady || initializedFromUrl) return;
    const { assay, disease, organism, reg } = router.query;
    if (typeof assay === "string") setAssayFilter(assay);
    if (typeof disease === "string") setDiseaseFilter(disease);
    if (typeof organism === "string") setOrganismFilter(organism);
    if (typeof reg === "string" && ["any", "up", "down"].includes(reg)) {
      setRegulation(reg as Regulation);
    }
    setInitializedFromUrl(true);
  }, [router.isReady, initializedFromUrl, router.query]);

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 900px)");
    setShowToc(mql.matches);
    const handler = (e: MediaQueryListEvent) => setShowToc(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  useEffect(() => {
    fetch("/api/dataset-tables-with-pvalues")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setDatasetTables(data.tables);
        setAssayTypeLabels(data.assayTypeLabels ?? {});
        setDiseaseTypeLabels(data.diseaseTypeLabels ?? {});
        setOrganismTypeLabels(data.organismTypeLabels ?? {});
        setDatasetsLoading(false);
      })
      .catch(() => setDatasetsLoading(false));
  }, []);

  const tocGroups = useAssayGroups(datasetTables, assayTypeLabels);

  // Derive available assay/disease filters from dataset tables
  const availableAssays = [
    ...new Set(
      datasetTables
        .flatMap((t) => t.assay ?? [])
        .filter(Boolean),
    ),
  ].sort();
  const availableDiseases = [
    ...new Set(
      datasetTables
        .flatMap((t) => t.disease ?? [])
        .filter(Boolean),
    ),
  ].sort();
  const availableOrganisms = [
    ...new Set(
      datasetTables
        .flatMap((t) => t.organismKey ?? [])
        .filter(Boolean),
    ),
  ].sort();

  const radioLabelStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    cursor: "pointer",
    color: "#4b5563",
    whiteSpace: "nowrap",
    fontSize: 14,
  };

  return (
    <>
      <Head>
        <title>Significant Rows by Dataset &mdash; SSPsyGene</title>
      </Head>
      <Header />
      <main
        style={{
          maxWidth: showToc ? 1200 : 1000,
          margin: "0 auto",
          padding: "24px 16px",
          color: "#1f2937",
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>
          Significant Rows (&lt; 0.05) by Dataset
        </h1>
        <p
          style={{
            color: "#4b5563",
            fontSize: 15,
            lineHeight: 1.7,
            marginBottom: 20,
          }}
        >
          Browse the most significant rows from each dataset table. Use the
          filters below to narrow by assay type, disease, and significance
          measure.{" "}
          <Link
            href="/most-significant"
            style={{ color: "#2563eb", textDecoration: "none" }}
          >
            See gene ranking by combined p-values &rarr;
          </Link>
        </p>

        {/* Regulation filter */}
        <div
          style={{
            marginBottom: 12,
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            padding: "10px 14px",
            fontSize: 13,
            display: "flex",
            alignItems: "center",
            gap: 14,
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              fontWeight: 600,
              color: "#374151",
              whiteSpace: "nowrap",
            }}
          >
            Regulation:
          </span>
          <label style={radioLabelStyle}>
            <input
              type="radio"
              name="regulationFilter"
              checked={regulation === "any"}
              onChange={() => setRegulation("any")}
            />
            All
          </label>
          <label style={radioLabelStyle}>
            <input
              type="radio"
              name="regulationFilter"
              checked={regulation === "up"}
              onChange={() => setRegulation("up")}
            />
            Up-regulated
          </label>
          <label style={radioLabelStyle}>
            <input
              type="radio"
              name="regulationFilter"
              checked={regulation === "down"}
              onChange={() => setRegulation("down")}
            />
            Down-regulated
          </label>
          <span style={{ color: "#6b7280", fontSize: 12 }}>
            Up/Down restricts to rows whose effect-size column is positive /
            negative; datasets without an effect column are hidden.
          </span>
        </div>

        {/* Assay type, disease, and organism filters */}
        {(availableAssays.length > 0 ||
          availableDiseases.length > 0 ||
          availableOrganisms.length > 0) && (
          <div
            style={{
              marginBottom: 12,
              background: "#f9fafb",
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              padding: "10px 14px",
              fontSize: 13,
            }}
          >
            {availableAssays.length > 0 && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  flexWrap: "wrap",
                  marginBottom:
                    availableDiseases.length > 0 ||
                    availableOrganisms.length > 0
                      ? 8
                      : 0,
                }}
              >
                <span
                  style={{
                    fontWeight: 600,
                    color: "#374151",
                    whiteSpace: "nowrap",
                  }}
                >
                  Assay type:
                </span>
                <label style={radioLabelStyle}>
                  <input
                    type="radio"
                    name="assayFilter"
                    checked={assayFilter === null}
                    onChange={() => setAssayFilter(null)}
                  />
                  All
                </label>
                {availableAssays.map((key) => (
                  <label key={key} style={radioLabelStyle}>
                    <input
                      type="radio"
                      name="assayFilter"
                      checked={assayFilter === key}
                      onChange={() => setAssayFilter(key)}
                    />
                    {assayTypeLabels[key] || key}
                  </label>
                ))}
              </div>
            )}
            {availableDiseases.length > 0 && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  flexWrap: "wrap",
                  marginBottom: availableOrganisms.length > 0 ? 8 : 0,
                }}
              >
                <span
                  style={{
                    fontWeight: 600,
                    color: "#374151",
                    whiteSpace: "nowrap",
                  }}
                >
                  Disease:
                </span>
                <label style={radioLabelStyle}>
                  <input
                    type="radio"
                    name="diseaseFilter"
                    checked={diseaseFilter === null}
                    onChange={() => setDiseaseFilter(null)}
                  />
                  All
                </label>
                {availableDiseases.map((key) => (
                  <label key={key} style={radioLabelStyle}>
                    <input
                      type="radio"
                      name="diseaseFilter"
                      checked={diseaseFilter === key}
                      onChange={() => setDiseaseFilter(key)}
                    />
                    {diseaseTypeLabels[key] || key}
                  </label>
                ))}
              </div>
            )}
            {availableOrganisms.length > 0 && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  flexWrap: "wrap",
                }}
              >
                <span
                  style={{
                    fontWeight: 600,
                    color: "#374151",
                    whiteSpace: "nowrap",
                  }}
                >
                  Organism:
                </span>
                <label style={radioLabelStyle}>
                  <input
                    type="radio"
                    name="organismFilter"
                    checked={organismFilter === null}
                    onChange={() => setOrganismFilter(null)}
                  />
                  All
                </label>
                {availableOrganisms.map((key) => (
                  <label key={key} style={radioLabelStyle}>
                    <input
                      type="radio"
                      name="organismFilter"
                      checked={organismFilter === key}
                      onChange={() => setOrganismFilter(key)}
                    />
                    {organismTypeLabels[key] || key}
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Filter/sort controls */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            marginBottom: 12,
            flexWrap: "wrap",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 13,
            }}
          >
            <span style={{ color: "#6b7280" }}>Rows where</span>
            <select
              value={sigFilterBy}
              onChange={(e) =>
                setSigFilterBy(e.target.value as "pvalue" | "fdr")
              }
              style={{
                padding: "4px 8px",
                borderRadius: 6,
                border: "1px solid #d1d5db",
                fontSize: 13,
              }}
            >
              <option value="pvalue">p-value</option>
              <option value="fdr">FDR</option>
            </select>
            <span style={{ color: "#6b7280" }}>&lt; 0.05, sorted by</span>
            <select
              value={sigSortBy}
              onChange={(e) => setSigSortBy(e.target.value as "pvalue" | "fdr")}
              style={{
                padding: "4px 8px",
                borderRadius: 6,
                border: "1px solid #d1d5db",
                fontSize: 13,
              }}
            >
              <option value="pvalue">p-value</option>
              <option value="fdr">FDR</option>
            </select>
          </div>
        </div>

        <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
          {showToc && tocGroups.length > 0 && (
            <DatasetToc groups={tocGroups} anchorPrefix="sig-dataset-" />
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            {datasetsLoading ? (
              <div style={{ color: "#6b7280", padding: "12px 0" }}>
                Loading datasets...
              </div>
            ) : (
              tocGroups
                .filter(
                  (group) => !assayFilter || group.assayKey === assayFilter,
                )
                .map((group) => {
                  const items = group.items as DatasetTableMeta[];
                  const filtered = items.filter((t) => {
                    const hasCol =
                      sigFilterBy === "pvalue" ? t.pvalueColumn : t.fdrColumn;
                    if (!hasCol) return false;
                    if (regulation !== "any" && !t.effectColumn) return false;
                    if (
                      diseaseFilter &&
                      !(t.disease ?? []).includes(diseaseFilter)
                    )
                      return false;
                    if (
                      organismFilter &&
                      !(t.organismKey ?? []).includes(organismFilter)
                    )
                      return false;
                    return true;
                  });
                  if (filtered.length === 0) return null;
                  return (
                    <div key={group.assayKey}>
                      {tocGroups.length > 1 && (
                        <div
                          style={{
                            marginTop: 24,
                            marginBottom: 6,
                            padding: "8px 0",
                            borderBottom: "2px solid #dbeafe",
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          <span
                            style={{
                              fontSize: 13,
                              fontWeight: 600,
                              color: "#1e40af",
                              backgroundColor: "#dbeafe",
                              borderRadius: 9999,
                              padding: "3px 10px",
                              textTransform: "uppercase",
                              letterSpacing: "0.03em",
                            }}
                          >
                            {group.label}
                          </span>
                          <span style={{ fontSize: 13, color: "#6b7280" }}>
                            {filtered.length} dataset
                            {filtered.length !== 1 ? "s" : ""}
                          </span>
                        </div>
                      )}
                      {filtered.map((t) => (
                        <div
                          key={t.tableName}
                          id={`sig-dataset-${t.tableName}`}
                          style={{ scrollMarginTop: 16 }}
                        >
                          <DatasetSection
                            meta={t}
                            filterBy={sigFilterBy}
                            sortBy={sigSortBy}
                            regulation={regulation}
                          />
                        </div>
                      ))}
                    </div>
                  );
                })
            )}
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}
