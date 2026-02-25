import { TableResult } from "@/lib/table_result";
import { useState, useEffect, useMemo, useRef, type ReactNode } from "react";
import DataTable from "@/components/DataTable";
import InfoTooltip from "@/components/InfoTooltip";
import { ROW_LIMIT } from "@/lib/gene-query";

const formatTableName = (section: TableResult) =>
  section.shortLabel ??
  section.tableName
    .replace(/_/g, " ")
    .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1));

const formatAuthors = (first: string | null | undefined, last: string | null | undefined, count: number | null | undefined) => {
  if (!first && !last) return "";
  if (first && last) {
    if (first === last) return first;
    return count != null && count > 2 ? `${first}, ..., ${last}` : `${first} & ${last}`;
  }
  if (first) return `${first} et al.`;
  return last ?? "";
};

type AssayGroup = {
  assayKey: string;
  label: string;
  sections: TableResult[];
};

type TablePageState = {
  page: number;
  rows: Record<string, unknown>[];
  totalRows: number;
  totalPages: number;
  loading: boolean;
  error: string | null;
};

export default function GeneResults({
  geneDisplayName,
  data,
  assayTypeLabels = {},
  centralGeneId,
  perturbedCentralGeneId,
  targetCentralGeneId,
}: {
  geneDisplayName: string | null;
  data: TableResult[];
  assayTypeLabels?: Record<string, string>;
  centralGeneId?: number;
  perturbedCentralGeneId?: number | null;
  targetCentralGeneId?: number | null;
}) {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set()
  );
  const [showToc, setShowToc] = useState(false);
  const [tablePageOverrides, setTablePageOverrides] = useState<Record<string, TablePageState>>({});
  const abortControllers = useRef<Record<string, AbortController>>({});

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 900px)");
    setShowToc(mql.matches);
    const handler = (e: MediaQueryListEvent) => setShowToc(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  // Reset pagination overrides when data changes (new gene selected)
  useEffect(() => {
    Object.values(abortControllers.current).forEach((c) => c.abort());
    abortControllers.current = {};
    setTablePageOverrides({});
  }, [data]);

  const fetchTablePage = async (tableName: string, page: number) => {
    // Abort any in-flight request for this table
    abortControllers.current[tableName]?.abort();
    const controller = new AbortController();
    abortControllers.current[tableName] = controller;

    setTablePageOverrides((prev) => ({
      ...prev,
      [tableName]: {
        page,
        rows: prev[tableName]?.rows ?? [],
        totalRows: prev[tableName]?.totalRows ?? 0,
        totalPages: prev[tableName]?.totalPages ?? 1,
        loading: true,
        error: null,
      },
    }));

    try {
      const body: Record<string, unknown> = { tableName, page };
      if (centralGeneId !== undefined) {
        body.centralGeneId = centralGeneId;
      } else {
        body.perturbedCentralGeneId = perturbedCentralGeneId ?? null;
        body.targetCentralGeneId = targetCentralGeneId ?? null;
      }

      const res = await fetch("/api/gene-table-page", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      const payload = await res.json();

      setTablePageOverrides((prev) => ({
        ...prev,
        [tableName]: {
          page: payload.page,
          rows: payload.rows,
          totalRows: payload.totalRows,
          totalPages: payload.totalPages,
          loading: false,
          error: null,
        },
      }));

      // Auto-expand the table when paginating
      setExpandedSections((prev) => new Set([...prev, tableName]));
    } catch (e: any) {
      if (e.name === "AbortError") return;
      setTablePageOverrides((prev) => ({
        ...prev,
        [tableName]: {
          ...prev[tableName]!,
          loading: false,
          error: e?.message || "Failed to load page",
        },
      }));
    }
  };

  const groups: AssayGroup[] = useMemo(() => {
    const groupMap = new Map<string, TableResult[]>();
    for (const section of data) {
      const key = section.assay?.[0] || "_other";
      if (!groupMap.has(key)) groupMap.set(key, []);
      groupMap.get(key)!.push(section);
    }

    // Build groups with labels
    const ordered: AssayGroup[] = [];
    for (const [k, sections] of groupMap) {
      ordered.push({
        assayKey: k,
        label: k === "_other" ? "Other" : (assayTypeLabels[k] ?? k),
        sections,
      });
    }

    // Sort groups alphabetically by label, keeping "_other" last
    ordered.sort((a, b) => {
      if (a.assayKey === "_other") return 1;
      if (b.assayKey === "_other") return -1;
      return a.label.localeCompare(b.label);
    });

    // Sort sections within each group alphabetically by display name
    for (const group of ordered) {
      group.sections.sort((a, b) =>
        formatTableName(a).localeCompare(formatTableName(b))
      );
    }

    return ordered;
  }, [data, assayTypeLabels]);

  const toggleSection = (name: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  if (!geneDisplayName) {
    return null;
  }

  const scrollTo = (id: string) => {
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const hasMultipleGroups = groups.length > 1;

  const renderPageNumbers = (
    currentPage: number,
    totalPages: number,
    tableName: string,
    isLoading: boolean
  ): ReactNode => {
    const items: ReactNode[] = [];
    if (totalPages <= 1) return null;

    const addBtn = (label: string | number, targetPage: number, key: string) => {
      const isActive = targetPage === currentPage;
      const isDisabled = isLoading || targetPage < 1 || targetPage > totalPages;
      items.push(
        <button
          key={key}
          onClick={() => !isDisabled && !isActive && fetchTablePage(tableName, targetPage)}
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
        <span key="pg-ell-1" style={{ color: "#6b7280", padding: "0 2px", fontSize: 13 }}>
          ...
        </span>
      );
    }

    surround.forEach((pnum) => addBtn(pnum, pnum, `pg-${pnum}`));

    if (surround.length > 0 && Math.max(...surround) < totalPages - 1) {
      items.push(
        <span key="pg-ell-2" style={{ color: "#6b7280", padding: "0 2px", fontSize: 13 }}>
          ...
        </span>
      );
    }

    if (totalPages > 2) addBtn(totalPages, totalPages, "pg-last");

    return (
      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
        {items}
      </div>
    );
  };

  const btnStyle = (disabled: boolean) => ({
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
    <div
      style={{
        width: showToc ? "min(1400px, 96%)" : "min(1100px, 96%)",
        margin: "28px auto",
        color: "#1f2937",
        display: "flex",
        gap: 24,
        alignItems: "flex-start",
      }}
    >
      {showToc && data.length > 0 && (
        <nav
          style={{
            width: 220,
            flexShrink: 0,
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            padding: "14px 0",
            marginTop: 50,
            position: "sticky",
            top: 16,
            maxHeight: "calc(100vh - 48px)",
            overflowY: "auto",
          }}
        >
          <div
            style={{
              padding: "0 14px 10px",
              fontWeight: 600,
              fontSize: 13,
              color: "#6b7280",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            Datasets
          </div>
          {groups.map((group) => (
            <div key={group.assayKey}>
              {hasMultipleGroups && (
                <div
                  style={{
                    padding: "8px 14px 4px",
                    fontSize: 12,
                    fontWeight: 600,
                    color: "#1e40af",
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    borderTop: "1px solid #e5e7eb",
                    marginTop: 4,
                  }}
                >
                  {group.label}
                </div>
              )}
              {group.sections.map((section) => (
                <button
                  key={section.tableName}
                  onClick={() => scrollTo(`table-${section.tableName}`)}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    padding: hasMultipleGroups
                      ? "6px 14px 6px 22px"
                      : "8px 14px",
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                    fontSize: 13,
                    color: "#2563eb",
                    lineHeight: 1.4,
                  }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.background = "#e5e7eb")
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.background = "transparent")
                  }
                >
                  {formatTableName(section)}
                </button>
              ))}
            </div>
          ))}
        </nav>
      )}
      <div style={{ flex: 1, minWidth: 0, marginLeft: showToc && data.length === 0 ? 244 : undefined }}>
        <h2 style={{ marginBottom: 12 }}>Results for {geneDisplayName}</h2>
        {data.length === 0 && (
          <div style={{ opacity: 0.8 }}>No results found in any dataset.</div>
        )}
        {groups.map((group) => (
          <div key={group.assayKey}>
            {hasMultipleGroups && (
              <div
                id={`assay-group-${group.assayKey}`}
                style={{
                  marginTop: 24,
                  marginBottom: 6,
                  padding: "8px 0",
                  borderBottom: "2px solid #dbeafe",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  scrollMarginTop: 16,
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
                  {group.sections.length} dataset
                  {group.sections.length !== 1 ? "s" : ""}
                </span>
              </div>
            )}
            {group.sections.map((section) => {
              const override = tablePageOverrides[section.tableName];
              const effectiveRows = override ? override.rows : section.rows;
              const effectiveTotalRows = override
                ? override.totalRows
                : (section.totalRows ?? section.rows.length);
              const effectivePage = override ? override.page : 1;
              const effectiveTotalPages = override
                ? override.totalPages
                : Math.max(1, Math.ceil(effectiveTotalRows / ROW_LIMIT));
              const isPageLoading = override?.loading ?? false;
              const pageError = override?.error ?? null;
              const hasPagination = effectiveTotalPages > 1;

              return (
                <div
                  key={section.tableName}
                  id={`table-${section.tableName}`}
                  style={{
                    marginTop: 18,
                    background: "#ffffff",
                    border: "1px solid #e5e7eb",
                    borderRadius: 12,
                    overflow: "hidden",
                    scrollMarginTop: 16,
                  }}
                >
                  <div
                    style={{
                      padding: "12px 14px",
                      borderBottom: "1px solid #e5e7eb",
                      fontWeight: 600,
                    }}
                  >
                    {formatTableName(section)}
                    {section.source && (
                      <InfoTooltip
                        text={`Source: ${section.source}`}
                        size={14}
                      />
                    )}
                  </div>
                  {section.description && (
                    <div
                      style={{
                        padding: "10px 14px",
                        color: "#6b7280",
                        fontSize: 14,
                      }}
                    >
                      {section.description}
                    </div>
                  )}
                  {(section.publicationFirstAuthor ||
                    section.publicationLastAuthor ||
                    section.publicationYear ||
                    section.publicationJournal ||
                    section.publicationDoi) && (
                    <div
                      style={{
                        padding: "4px 14px 8px",
                        fontSize: 13,
                        color: "#6b7280",
                      }}
                    >
                      <span style={{ fontWeight: 500 }}>Publication:</span>{" "}
                      {formatAuthors(section.publicationFirstAuthor, section.publicationLastAuthor, section.publicationAuthorCount)}
                      {section.publicationYear ? ` (${section.publicationYear})` : ""}
                      {section.publicationJournal ? `, ${section.publicationJournal}` : ""}
                      {section.publicationDoi && (
                        <>
                          {", "}
                          <a
                            href={`https://doi.org/${section.publicationDoi}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: "#2563eb", textDecoration: "underline" }}
                          >
                            DOI: {section.publicationDoi}
                          </a>
                        </>
                      )}
                    </div>
                  )}
                  {expandedSections.has(section.tableName) &&
                    effectiveRows.length > 5 && (
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "flex-end",
                          padding: "6px 14px",
                          background: "#f9fafb",
                          borderBottom: "1px solid #e5e7eb",
                        }}
                      >
                        <button
                          onClick={() => toggleSection(section.tableName)}
                          style={{
                            padding: "6px 12px",
                            background: "#ffffff",
                            border: "1px solid #d1d5db",
                            color: "#1f2937",
                            borderRadius: 10,
                            fontSize: 13,
                            fontWeight: 500,
                            cursor: "pointer",
                          }}
                        >
                          Collapse
                        </button>
                      </div>
                    )}
                  <div style={{
                    opacity: isPageLoading ? 0.5 : 1,
                    pointerEvents: isPageLoading ? "none" : "auto",
                    position: "relative",
                    transition: "opacity 0.15s",
                  }}>
                    <DataTable
                      columns={section.displayColumns}
                      rows={effectiveRows}
                      maxRows={
                        expandedSections.has(section.tableName) ? undefined : 5
                      }
                      totalRows={effectiveTotalRows}
                      scalarColumns={section.scalarColumns}
                      fieldLabels={section.fieldLabels}
                      showSummary={false}
                    />
                    {isPageLoading && (
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
                  {pageError && (
                    <div style={{
                      padding: "8px 14px",
                      fontSize: 13,
                      color: "#dc2626",
                      borderTop: "1px solid #e5e7eb",
                      background: "#fef2f2",
                    }}>
                      Failed to load page. {pageError}
                    </div>
                  )}
                  {(() => {
                    const showFooter = effectiveRows.length > 5 || hasPagination;
                    if (!showFooter) return null;
                    const isExpanded = expandedSections.has(section.tableName);
                    const visibleCount = isExpanded
                      ? effectiveRows.length
                      : Math.min(5, effectiveRows.length);

                    // Summary text
                    let summaryText: string;
                    if (hasPagination) {
                      const rangeStart = (effectivePage - 1) * ROW_LIMIT + 1;
                      const rangeEnd = rangeStart + effectiveRows.length - 1;
                      summaryText = `Showing ${visibleCount.toLocaleString()} of rows ${rangeStart.toLocaleString()}\u2013${rangeEnd.toLocaleString()} (${effectiveTotalRows.toLocaleString()} total)`;
                    } else if (isExpanded) {
                      summaryText = `Showing all ${effectiveRows.length}`;
                    } else {
                      summaryText = `Showing 5 of ${effectiveRows.length}`;
                    }

                    return (
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
                          {summaryText}
                        </div>
                        {hasPagination && isExpanded && (
                          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                            <button
                              disabled={effectivePage <= 1 || isPageLoading}
                              onClick={() => fetchTablePage(section.tableName, effectivePage - 1)}
                              style={btnStyle(effectivePage <= 1 || isPageLoading)}
                            >
                              Prev
                            </button>
                            {renderPageNumbers(effectivePage, effectiveTotalPages, section.tableName, isPageLoading)}
                            <button
                              disabled={effectivePage >= effectiveTotalPages || isPageLoading}
                              onClick={() => fetchTablePage(section.tableName, effectivePage + 1)}
                              style={btnStyle(effectivePage >= effectiveTotalPages || isPageLoading)}
                            >
                              Next
                            </button>
                          </div>
                        )}
                        {effectiveRows.length > 5 && (
                          <button
                            onClick={() => toggleSection(section.tableName)}
                            style={{
                              padding: "8px 12px",
                              background: "#ffffff",
                              border: "1px solid #d1d5db",
                              color: "#1f2937",
                              borderRadius: 10,
                              fontSize: 14,
                              fontWeight: 500,
                              cursor: "pointer",
                            }}
                          >
                            {isExpanded ? "Collapse" : "Expand"}
                          </button>
                        )}
                      </div>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
