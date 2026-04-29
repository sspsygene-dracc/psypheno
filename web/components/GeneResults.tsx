import { TableResult } from "@/lib/table_result";
import { useState, useEffect, useMemo, useRef, type ReactNode } from "react";
import Link from "next/link";
import DataTable, { type SortMode } from "@/components/DataTable";
import DatasetToc from "@/components/DatasetToc";
import GeneInfoBox, { type LlmResult } from "@/components/GeneInfoBox";
import InfoTooltip from "@/components/InfoTooltip";
import GeneSignificanceSummary, {
  type CombinedPvalues,
  type ContributingTable,
} from "@/components/GeneSignificanceSummary";
import EffectDistributionChart from "@/components/EffectDistributionChart";
import { ROW_LIMIT } from "@/lib/gene-query";
import { formatAuthors } from "@/lib/format-authors";
import type { SearchSuggestion } from "@/state/SearchSuggestion";

const formatTableName = (section: TableResult) =>
  section.mediumLabel ??
  section.tableName
    .replace(/_/g, " ")
    .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1));

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

type TableSortState = {
  sortBy: string | null;
  sortMode: SortMode;
};

type GeneInfoData = {
  geneDescription: string | null;
  llmResult: LlmResult | null;
  combinedPvalues: CombinedPvalues | null;
  contributingTables: ContributingTable[];
};

export default function GeneResults({
  geneDisplayName,
  data,
  assayTypeLabels = {},
  perturbedGene,
  targetGene,
}: {
  geneDisplayName: string | null;
  data: TableResult[];
  assayTypeLabels?: Record<string, string>;
  perturbedGene: SearchSuggestion | null;
  targetGene: SearchSuggestion | null;
}) {
  const perturbedCentralGeneId = perturbedGene?.centralGeneId ?? null;
  const targetCentralGeneId = targetGene?.centralGeneId ?? null;
  const [perturbedInfo, setPerturbedInfo] = useState<GeneInfoData | null>(null);
  const [targetInfo, setTargetInfo] = useState<GeneInfoData | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (perturbedCentralGeneId == null) {
      setPerturbedInfo(null);
      return;
    }
    fetch("/api/combined-pvalues", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        centralGeneId: perturbedCentralGeneId,
        direction: "perturbed",
      }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d) return;
        setPerturbedInfo({
          geneDescription: d.geneDescription ?? null,
          llmResult: d.llmResult ?? null,
          combinedPvalues: d.combinedPvalues ?? null,
          contributingTables: d.contributingTables ?? [],
        });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [perturbedCentralGeneId]);

  useEffect(() => {
    let cancelled = false;
    if (targetCentralGeneId == null) {
      setTargetInfo(null);
      return;
    }
    fetch("/api/combined-pvalues", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        centralGeneId: targetCentralGeneId,
        direction: "target",
      }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d) return;
        setTargetInfo({
          geneDescription: d.geneDescription ?? null,
          llmResult: d.llmResult ?? null,
          combinedPvalues: d.combinedPvalues ?? null,
          contributingTables: d.contributingTables ?? [],
        });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [targetCentralGeneId]);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(),
  );
  const [expandedDistributions, setExpandedDistributions] = useState<
    Set<string>
  >(new Set());
  const toggleDistribution = (tableName: string) =>
    setExpandedDistributions((prev) => {
      const next = new Set(prev);
      if (next.has(tableName)) next.delete(tableName);
      else next.add(tableName);
      return next;
    });
  const [showToc, setShowToc] = useState(false);
  const [tablePageOverrides, setTablePageOverrides] = useState<
    Record<string, TablePageState>
  >({});
  const [tableSortStates, setTableSortStates] = useState<
    Record<string, TableSortState>
  >({});
  const abortControllers = useRef<Record<string, AbortController>>({});

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 900px)");
    setShowToc(mql.matches);
    const handler = (e: MediaQueryListEvent) => setShowToc(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  // Reset pagination overrides and seed default expansion + sort state when
  // data changes (new gene selected).
  //   #90: expand p-value tables and volcano plots by default.
  //   #86: mark each table's initial sort to match what the API pre-sorted by
  //   (FDR or pvalue ascending). Cosmetic — doesn't trigger a re-fetch.
  useEffect(() => {
    Object.values(abortControllers.current).forEach((c) => c.abort());
    abortControllers.current = {};
    setTablePageOverrides({});

    setExpandedSections(
      new Set(
        data
          .filter((s) => s.pvalueColumn || s.fdrColumn)
          .map((s) => s.tableName),
      ),
    );

    setExpandedDistributions(
      new Set(data.filter((s) => s.effectColumn).map((s) => s.tableName)),
    );

    const initialSorts: Record<string, TableSortState> = {};
    for (const s of data) {
      const src = s.fdrColumn ?? s.pvalueColumn;
      if (!src) continue;
      const col = src.split(",")[0]?.trim();
      if (col) initialSorts[s.tableName] = { sortBy: col, sortMode: "asc" };
    }
    setTableSortStates(initialSorts);
  }, [data]);

  const scrollToTableTop = (tableName: string) => {
    const tableEl = document.getElementById(`table-${tableName}`);
    if (!tableEl) return;
    tableEl.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const fetchTablePage = async (
    tableName: string,
    page: number,
    sortBy?: string | null,
    sortMode?: SortMode,
  ) => {
    scrollToTableTop(tableName);

    // Abort any in-flight request for this table
    abortControllers.current[tableName]?.abort();
    const controller = new AbortController();
    abortControllers.current[tableName] = controller;
    const baseSection = data.find((section) => section.tableName === tableName);
    const fallbackRows = baseSection?.rows ?? [];
    const fallbackTotalRows =
      baseSection?.totalRows ?? baseSection?.rows.length ?? 0;
    const fallbackTotalPages = Math.max(
      1,
      Math.ceil(fallbackTotalRows / ROW_LIMIT),
    );

    setTablePageOverrides((prev) => ({
      ...prev,
      [tableName]: {
        page,
        rows: prev[tableName]?.rows ?? fallbackRows,
        totalRows: prev[tableName]?.totalRows ?? fallbackTotalRows,
        totalPages: prev[tableName]?.totalPages ?? fallbackTotalPages,
        loading: true,
        error: null,
      },
    }));

    try {
      const body: Record<string, unknown> = {
        tableName,
        page,
        perturbedCentralGeneId,
        targetCentralGeneId,
      };
      // Add sort params if present
      if (sortBy && sortMode && sortMode !== "none") {
        body.sortBy = sortBy;
        body.sortMode = sortMode;
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

  const handleTableSort = (
    tableName: string,
    column: string,
    mode: SortMode,
  ) => {
    const newSortState: TableSortState = {
      sortBy: mode === "none" ? null : column,
      sortMode: mode,
    };
    setTableSortStates((prev) => ({ ...prev, [tableName]: newSortState }));

    if (mode === "none") {
      // Clear override to go back to original data
      setTablePageOverrides((prev) => {
        const next = { ...prev };
        delete next[tableName];
        return next;
      });
    } else {
      fetchTablePage(tableName, 1, column, mode);
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
        formatTableName(a).localeCompare(formatTableName(b)),
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

  const hasMultipleGroups = groups.length > 1;
  const hasSignificanceColumns = data.some(
    (s) => s.pvalueColumn || s.fdrColumn,
  );

  const renderPageNumbers = (
    currentPage: number,
    totalPages: number,
    tableName: string,
    isLoading: boolean,
  ): ReactNode => {
    const items: ReactNode[] = [];
    if (totalPages <= 1) return null;

    const currentSort = tableSortStates[tableName];

    const addBtn = (
      label: string | number,
      targetPage: number,
      key: string,
    ) => {
      const isActive = targetPage === currentPage;
      const isDisabled = isLoading || targetPage < 1 || targetPage > totalPages;
      items.push(
        <button
          key={key}
          onClick={() =>
            !isDisabled &&
            !isActive &&
            fetchTablePage(
              tableName,
              targetPage,
              currentSort?.sortBy,
              currentSort?.sortMode,
            )
          }
          disabled={isDisabled}
          aria-current={isActive ? "page" : undefined}
          style={{
            padding: "4px 8px",
            minWidth: 30,
            background: isActive
              ? "#e5e7eb"
              : isDisabled
                ? "#f9fafb"
                : "#ffffff",
            border: "1px solid #d1d5db",
            color: "#1f2937",
            borderRadius: 6,
            cursor: isDisabled || isActive ? "default" : "pointer",
            fontWeight: isActive ? 700 : 500,
            fontSize: 13,
          }}
        >
          {label}
        </button>,
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
        <span
          key="pg-ell-1"
          style={{ color: "#6b7280", padding: "0 2px", fontSize: 13 }}
        >
          ...
        </span>,
      );
    }

    surround.forEach((pnum) => addBtn(pnum, pnum, `pg-${pnum}`));

    if (surround.length > 0 && Math.max(...surround) < totalPages - 1) {
      items.push(
        <span
          key="pg-ell-2"
          style={{ color: "#6b7280", padding: "0 2px", fontSize: 13 }}
        >
          ...
        </span>,
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
    cursor: disabled ? "not-allowed" : ("pointer" as const),
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
        <DatasetToc
          groups={groups.map((g) => ({
            assayKey: g.assayKey,
            label: g.label,
            items: g.sections,
          }))}
          anchorPrefix="table-"
          style={{ marginTop: 50 }}
        />
      )}
      <div
        style={{
          flex: 1,
          minWidth: 0,
          marginLeft: showToc && data.length === 0 ? 244 : undefined,
        }}
      >
        <h2 style={{ marginBottom: 12 }}>Results for {geneDisplayName}</h2>
        {hasSignificanceColumns && (
          <div
            style={{
              marginBottom: 12,
              fontSize: 13,
              color: "#374151",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span
              aria-hidden="true"
              style={{
                display: "inline-block",
                width: 14,
                height: 14,
                background: "#f0fdf4",
                border: "1px solid #86efac",
                borderRadius: 3,
              }}
            />
            <span>
              Rows highlighted in green have FDR or p &lt; 0.05 (FDR is used
              when available).
            </span>
          </div>
        )}
        {perturbedGene && (
          <GeneSidePanel
            label="Perturbed"
            geneSymbol={perturbedGene.humanSymbol ?? "—"}
            info={perturbedInfo}
            assayTypeLabels={assayTypeLabels}
          />
        )}
        {targetGene && (
          <GeneSidePanel
            label="Target"
            geneSymbol={targetGene.humanSymbol ?? "—"}
            info={targetInfo}
            assayTypeLabels={assayTypeLabels}
          />
        )}
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
              const currentSort = tableSortStates[section.tableName];

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
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 12,
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      {formatTableName(section)}
                      {section.source && (
                        <InfoTooltip
                          text={`Source: ${section.source}`}
                          size={14}
                        />
                      )}
                    </div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        flexShrink: 0,
                        flexWrap: "wrap",
                        fontSize: 13,
                        fontWeight: 500,
                      }}
                    >
                      <a
                        href={`/api/download/tables/${encodeURIComponent(section.tableName)}.tsv`}
                        style={{
                          padding: "3px 8px",
                          background: "#ffffff",
                          border: "1px solid #d1d5db",
                          borderRadius: 6,
                          color: "#1f2937",
                          textDecoration: "none",
                          whiteSpace: "nowrap",
                        }}
                        title="Download the full table as TSV"
                      >
                        TSV
                      </a>
                      <a
                        href={`/api/download/metadata/${encodeURIComponent(section.tableName)}.yaml`}
                        style={{
                          padding: "3px 8px",
                          background: "#ffffff",
                          border: "1px solid #d1d5db",
                          borderRadius: 6,
                          color: "#1f2937",
                          textDecoration: "none",
                          whiteSpace: "nowrap",
                        }}
                        title="Download metadata YAML"
                      >
                        YAML
                      </a>
                      <Link
                        href={`/full-datasets?open=${encodeURIComponent(
                          section.shortLabel
                            ? section.shortLabel.replace(/\s+/g, "_")
                            : section.tableName,
                        )}`}
                        style={{
                          color: "#2563eb",
                          textDecoration: "none",
                          whiteSpace: "nowrap",
                        }}
                        title="Open the full data table for this dataset"
                      >
                        View full data table →
                      </Link>
                    </div>
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
                      {formatAuthors(
                        section.publicationFirstAuthor,
                        section.publicationLastAuthor,
                        section.publicationAuthorCount,
                      )}
                      {section.publicationYear
                        ? ` (${section.publicationYear})`
                        : ""}
                      {section.publicationJournal
                        ? `, ${section.publicationJournal}`
                        : ""}
                      {section.publicationDoi && (
                        <>
                          {", "}
                          <a
                            href={`https://doi.org/${section.publicationDoi}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              color: "#2563eb",
                              textDecoration: "underline",
                            }}
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
                  <div
                    style={{
                      opacity: isPageLoading ? 0.5 : 1,
                      pointerEvents: isPageLoading ? "none" : "auto",
                      position: "relative",
                      transition: "opacity 0.15s",
                    }}
                  >
                    <DataTable
                      columns={section.displayColumns}
                      rows={effectiveRows}
                      maxRows={
                        expandedSections.has(section.tableName) ? undefined : 5
                      }
                      totalRows={effectiveTotalRows}
                      scalarColumns={section.scalarColumns}
                      fieldLabels={section.fieldLabels}
                      geneColumns={section.geneColumns}
                      pvalueColumn={section.pvalueColumn}
                      fdrColumn={section.fdrColumn}
                      showSummary={false}
                      sortColumn={currentSort?.sortBy ?? null}
                      sortMode={currentSort?.sortMode ?? "none"}
                      onSort={(col, mode) =>
                        handleTableSort(section.tableName, col, mode)
                      }
                    />
                    {isPageLoading && (
                      <div
                        style={{
                          position: "absolute",
                          top: "50%",
                          left: "50%",
                          transform: "translate(-50%, -50%)",
                          fontSize: 14,
                          color: "#6b7280",
                          background: "rgba(255, 255, 255, 0.92)",
                          border: "1px solid #d1d5db",
                          borderRadius: 9999,
                          padding: "6px 12px",
                        }}
                      >
                        Loading page {effectivePage}...
                      </div>
                    )}
                  </div>
                  {pageError && (
                    <div
                      style={{
                        padding: "8px 14px",
                        fontSize: 13,
                        color: "#dc2626",
                        borderTop: "1px solid #e5e7eb",
                        background: "#fef2f2",
                      }}
                    >
                      Failed to load page. {pageError}
                    </div>
                  )}
                  {(() => {
                    const showFooter =
                      effectiveRows.length > 5 || hasPagination;
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
                          <div
                            style={{
                              display: "flex",
                              gap: 6,
                              alignItems: "center",
                            }}
                          >
                            <button
                              disabled={effectivePage <= 1 || isPageLoading}
                              onClick={() =>
                                fetchTablePage(
                                  section.tableName,
                                  effectivePage - 1,
                                  currentSort?.sortBy,
                                  currentSort?.sortMode,
                                )
                              }
                              style={btnStyle(
                                effectivePage <= 1 || isPageLoading,
                              )}
                            >
                              Prev
                            </button>
                            {renderPageNumbers(
                              effectivePage,
                              effectiveTotalPages,
                              section.tableName,
                              isPageLoading,
                            )}
                            <button
                              disabled={
                                effectivePage >= effectiveTotalPages ||
                                isPageLoading
                              }
                              onClick={() =>
                                fetchTablePage(
                                  section.tableName,
                                  effectivePage + 1,
                                  currentSort?.sortBy,
                                  currentSort?.sortMode,
                                )
                              }
                              style={btnStyle(
                                effectivePage >= effectiveTotalPages ||
                                  isPageLoading,
                              )}
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
                  {section.effectColumn && (
                    <div
                      style={{
                        borderTop: "1px solid #e5e7eb",
                        background: "#f8fafc",
                      }}
                    >
                      <button
                        type="button"
                        onClick={() => toggleDistribution(section.tableName)}
                        style={{
                          width: "100%",
                          padding: "8px 14px",
                          background: "none",
                          border: "none",
                          cursor: "pointer",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          fontSize: 13,
                          fontWeight: 600,
                          color: "#1e40af",
                        }}
                      >
                        <span>
                          Volcano plot ({section.effectColumn} vs p-value)
                        </span>
                        <span style={{ fontSize: 12, color: "#6b7280" }}>
                          {expandedDistributions.has(section.tableName)
                            ? "▲ Hide"
                            : "▼ Show"}
                        </span>
                      </button>
                      {expandedDistributions.has(section.tableName) && (
                        <div style={{ padding: "0 14px 14px" }}>
                          <EffectDistributionChart
                            tableName={section.tableName}
                            perturbedCentralGeneId={
                              perturbedCentralGeneId ?? undefined
                            }
                            targetCentralGeneId={
                              targetCentralGeneId ?? undefined
                            }
                            geneSymbol={geneDisplayName ?? undefined}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function GeneSidePanel({
  label,
  geneSymbol,
  info,
  assayTypeLabels,
}: {
  label: "Perturbed" | "Target";
  geneSymbol: string;
  info: GeneInfoData | null;
  assayTypeLabels: Record<string, string>;
}) {
  return (
    <div
      style={{
        marginBottom: 16,
        padding: "12px 14px",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
      }}
    >
      <div
        style={{
          fontSize: 13,
          fontWeight: 600,
          color: "#1e40af",
          marginBottom: 8,
          textTransform: "uppercase",
          letterSpacing: "0.04em",
        }}
      >
        {label} gene: {geneSymbol}
      </div>
      <GeneInfoBox
        geneDescription={info?.geneDescription ?? null}
        llmResult={info?.llmResult ?? null}
      />
      {info && info.combinedPvalues && (
        <GeneSignificanceSummary
          combinedPvalues={info.combinedPvalues}
          contributingTables={info.contributingTables}
          assayTypeLabels={assayTypeLabels}
        />
      )}
    </div>
  );
}
