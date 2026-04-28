import { useState, useMemo, useEffect } from "react";
import Link from "next/link";
import InfoTooltip from "@/components/InfoTooltip";

function normalizeColName(s: string): string {
  return s.trim().toLowerCase().replace(/\s+/g, "_");
}

/** Format a numeric value to avoid floating-point display artifacts. */
function formatNumber(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  if (n === 0) return "0";
  const abs = Math.abs(n);
  // Very small or very large: use exponential notation with 4 significant digits
  if (abs < 0.001 || abs >= 1e6) return n.toExponential(3);
  // Otherwise use toPrecision to avoid artifacts like 1.0999999999998
  return n.toPrecision(4);
}

function formatCellValue(val: unknown): string {
  if (val == null) return "";
  if (typeof val === "number") return formatNumber(val);
  return String(val);
}

function formatColumnHeader(col: string): string {
  return col
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export type SortMode = "none" | "asc" | "desc" | "asc_abs" | "desc_abs";

export const SIGNIFICANCE_THRESHOLD = 0.05;

function parseSignificanceColumns(spec?: string | null): string[] {
  if (!spec) return [];
  return spec.split(",").map((s) => s.trim()).filter(Boolean);
}

function isRowSignificant(
  row: Record<string, unknown>,
  cols: string[],
): boolean {
  for (const col of cols) {
    const v = row[col];
    if (v == null) continue;
    const n = typeof v === "number" ? v : Number(v);
    if (Number.isFinite(n) && n < SIGNIFICANCE_THRESHOLD) return true;
  }
  return false;
}

function sortIndicator(mode: SortMode): string {
  switch (mode) {
    case "asc": return " \u25B2";
    case "desc": return " \u25BC";
    case "asc_abs": return " |\u25B2|";
    case "desc_abs": return " |\u25BC|";
    default: return " \u21C5";
  }
}

export function computeNextSortMode(
  clickedCol: string,
  currentCol: string | null,
  currentMode: SortMode,
  scalarSet: Set<string>,
): SortMode {
  if (clickedCol !== currentCol) return "asc";
  const isScalar = scalarSet.has(clickedCol);
  const cycle: SortMode[] = isScalar
    ? ["asc", "desc", "asc_abs", "desc_abs", "none"]
    : ["asc", "desc", "none"];
  const idx = cycle.indexOf(currentMode);
  return cycle[(idx + 1) % cycle.length];
}

export default function DataTable({
  columns,
  rows,
  maxRows,
  totalRows,
  showSummary = true,
  scalarColumns,
  fieldLabels,
  geneColumns,
  pvalueColumn,
  fdrColumn,
  sortColumn: controlledSortColumn,
  sortMode: controlledSortMode,
  onSort,
  columnFilters,
  onColumnFilterChange,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  maxRows?: number;
  totalRows?: number;
  showSummary?: boolean;
  scalarColumns?: string[];
  fieldLabels?: Record<string, string> | null;
  geneColumns?: string[];
  pvalueColumn?: string | null;
  fdrColumn?: string | null;
  sortColumn?: string | null;
  sortMode?: SortMode;
  onSort?: (column: string, mode: SortMode) => void;
  columnFilters?: Record<string, string>;
  onColumnFilterChange?: (column: string, value: string) => void;
}) {
  const isControlled = onSort !== undefined;

  const [internalSortColumn, setInternalSortColumn] = useState<string | null>(null);
  const [internalSortMode, setInternalSortMode] = useState<SortMode>("none");

  const effectiveSortColumn = isControlled ? (controlledSortColumn ?? null) : internalSortColumn;
  const effectiveSortMode = isControlled ? (controlledSortMode ?? "none") : internalSortMode;

  const scalarSet = useMemo(() => {
    return new Set(scalarColumns ?? []);
  }, [scalarColumns, columns]);

  // Reset sort when data changes (uncontrolled mode only)
  useEffect(() => {
    if (!isControlled) {
      setInternalSortColumn(null);
      setInternalSortMode("none");
    }
  }, [columns, rows, isControlled]);

  const handleHeaderClick = (col: string) => {
    const nextMode = computeNextSortMode(col, effectiveSortColumn, effectiveSortMode, scalarSet);
    if (isControlled) {
      onSort!(col, nextMode);
    } else {
      setInternalSortColumn(nextMode === "none" ? null : col);
      setInternalSortMode(nextMode);
    }
  };

  const sortedRows = useMemo(() => {
    if (isControlled || !effectiveSortColumn || effectiveSortMode === "none") return rows;

    const isAbsSort = effectiveSortMode === "asc_abs" || effectiveSortMode === "desc_abs";
    const isAsc = effectiveSortMode === "asc" || effectiveSortMode === "asc_abs";
    const isScalar = scalarSet.has(effectiveSortColumn);
    const col = effectiveSortColumn;

    return [...rows].sort((a, b) => {
      const va = a[col];
      const vb = b[col];

      // Nulls always sort to end
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;

      let cmp: number;
      if (isScalar) {
        let na = Number(va);
        let nb = Number(vb);
        if (isNaN(na) && isNaN(nb)) return 0;
        if (isNaN(na)) return 1;
        if (isNaN(nb)) return -1;
        if (isAbsSort) {
          na = Math.abs(na);
          nb = Math.abs(nb);
        }
        cmp = na - nb;
      } else {
        cmp = String(va).localeCompare(String(vb));
      }

      return isAsc ? cmp : -cmp;
    });
  }, [rows, effectiveSortColumn, effectiveSortMode, scalarSet, isControlled]);

  const rowsToDisplay = maxRows ? sortedRows.slice(0, maxRows) : sortedRows;

  // Prefer FDR (already multiple-testing corrected) over raw p-value.
  const sigSourceColumn = fdrColumn ?? pvalueColumn ?? null;
  const sigCols = useMemo(
    () => parseSignificanceColumns(sigSourceColumn),
    [sigSourceColumn],
  );
  const sigTitle = sigSourceColumn
    ? `Significant: ${sigSourceColumn} < ${SIGNIFICANCE_THRESHOLD}`
    : undefined;

  // Priority-based render-side column reorder:
  //   tier 1 = gene columns, tier 2 = significance columns, tier 3 = the rest.
  // Source order is preserved within each tier. Row data is keyed by name,
  // so cell lookups don't depend on column order.
  const effectiveColumns = useMemo(() => {
    const t1Names = new Set((geneColumns ?? []).map(normalizeColName));
    const sigNamesAll = [
      ...parseSignificanceColumns(pvalueColumn),
      ...parseSignificanceColumns(fdrColumn),
    ].map(normalizeColName);
    const t2Names = new Set(
      sigNamesAll.filter((c) => !t1Names.has(c)),
    );
    const inT1: string[] = [];
    const inT2: string[] = [];
    const inT3: string[] = [];
    for (const c of columns) {
      const n = normalizeColName(c);
      if (t1Names.has(n)) inT1.push(c);
      else if (t2Names.has(n)) inT2.push(c);
      else inT3.push(c);
    }
    return [...inT1, ...inT2, ...inT3];
  }, [columns, geneColumns, pvalueColumn, fdrColumn]);

  const isActive = (col: string) =>
    col === effectiveSortColumn && effectiveSortMode !== "none";

  const showFilterRow = onColumnFilterChange !== undefined;
  const filterPlaceholder = (col: string) =>
    scalarSet.has(col) ? "e.g. >0.5" : "Filter...";

  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: 14,
        }}
      >
        <thead>
          <tr style={{ background: "#f9fafb" }}>
            {effectiveColumns.map((col) => {
              const active = isActive(col);
              return (
                <th
                  key={col}
                  onClick={() => handleHeaderClick(col)}
                  style={{
                    padding: "12px 16px",
                    textAlign: "left",
                    color: active ? "#1f2937" : "#6b7280",
                    fontWeight: 600,
                    borderTop: "1px solid #e5e7eb",
                    whiteSpace: "nowrap",
                    cursor: "pointer",
                    userSelect: "none",
                  }}
                >
                  {formatColumnHeader(col)}
                  {fieldLabels?.[col] && (
                    <InfoTooltip text={fieldLabels[col]} size={13} />
                  )}
                  <span
                    style={{
                      fontSize: active ? 12 : 18,
                      marginLeft: 4,
                      color: active ? "#1f2937" : "#9ca3af",
                    }}
                  >
                    {sortIndicator(active ? effectiveSortMode : "none")}
                  </span>
                </th>
              );
            })}
          </tr>
          {showFilterRow && (
            <tr style={{ background: "#ffffff" }}>
              {effectiveColumns.map((col) => (
                <th
                  key={col}
                  style={{
                    padding: "6px 16px 8px",
                    borderTop: "1px solid #f3f4f6",
                    fontWeight: 400,
                  }}
                >
                  <input
                    type="text"
                    value={columnFilters?.[col] ?? ""}
                    onChange={(e) =>
                      onColumnFilterChange!(col, e.target.value)
                    }
                    placeholder={filterPlaceholder(col)}
                    aria-label={`Filter ${formatColumnHeader(col)}`}
                    style={{
                      width: "100%",
                      minWidth: 80,
                      padding: "4px 8px",
                      border: "1px solid #d1d5db",
                      borderRadius: 6,
                      fontSize: 13,
                      color: "#1f2937",
                      background: "#ffffff",
                      boxSizing: "border-box",
                    }}
                  />
                </th>
              ))}
            </tr>
          )}
        </thead>
        <tbody>
          {rowsToDisplay.map((row, idx) => {
            const significant =
              sigCols.length > 0 && isRowSignificant(row, sigCols);
            return (
            <tr
              key={idx}
              style={{
                borderTop: "1px solid #e5e7eb",
                background: significant ? "#f0fdf4" : undefined,
              }}
              title={significant ? sigTitle : undefined}
            >
              {effectiveColumns.map((col) => {
                const val = row[col];
                const colNorm = normalizeColName(col);
                const isGeneCol = geneColumns?.some(
                  (g) => normalizeColName(g) === colNorm,
                );
                const text = formatCellValue(val);
                return (
                  <td
                    key={col}
                    style={{
                      padding: "12px 16px",
                      color: "#1f2937",
                    }}
                  >
                    {isGeneCol && text ? (
                      <Link
                        href={`/?searchmode=general&selected=${encodeURIComponent(text)}`}
                        style={{
                          color: "#2563eb",
                          textDecoration: "none",
                          fontWeight: 500,
                        }}
                      >
                        {text}
                      </Link>
                    ) : (
                      text
                    )}
                  </td>
                );
              })}
            </tr>
            );
          })}
        </tbody>
      </table>
      {showSummary && (
        <div
          style={{
            padding: 16,
            textAlign: "center",
            color: "#6b7280",
            fontSize: 14,
            borderTop: "1px solid #e5e7eb",
          }}
        >
          {(() => {
            const shown = maxRows
              ? Math.min(rows.length, maxRows)
              : rows.length;
            const total = totalRows ?? rows.length;
            return `Showing ${shown} of ${total} rows`;
          })()}
        </div>
      )}
    </div>
  );
}
