import { useMemo, useState } from "react";
import DoubleScrollX from "@/components/DoubleScrollX";
import type { CellStatus } from "@/pages/api/collated-matrix";

/**
 * CollatedMatrix — the perturbed-gene × modality "red table" (psypheno #213,
 * epic #220), rendered as a compact status heatmap. Rows are experimentally-
 * perturbed genes, columns are experimental modalities, and each cell is a
 * small color-coded tile whose fill encodes a status (not an effect size).
 * Sparse by design: most tiles are "no data" (near-empty), so signal pops.
 *
 * Consumes the shape returned by GET /api/collated-matrix. That route exports
 * `CellStatus`; the record types below mirror its file-private interfaces.
 *
 * A DataTable config can't express this (sticky header + frozen first column),
 * so this is a purpose-built component. Horizontal scroll + sticky axes are
 * handled by a bounded-height DoubleScrollX (see MATRIX_MAX_HEIGHT).
 */

export interface MatrixCell {
  status: CellStatus;
  count: number;
  tableNames: string[];
}

export interface MatrixGeneRow {
  centralGeneId: number;
  humanSymbol: string | null;
  cells: Record<string, MatrixCell>;
}

export interface MatrixModalityColumn {
  key: string;
  label: string;
  alwaysShow: boolean;
  isEmpty: boolean;
}

type SortMode = "symbol" | "sig";

// Bounded scroll region: makes DoubleScrollX's content div a vertical scroll
// container so the sticky header + frozen column resolve against it, not the
// page (an unbounded overflow ancestor would defeat `position: sticky; top`).
const MATRIX_MAX_HEIGHT = "72vh";
const TILE = 15; // color tile edge, px
const CELL = 17; // tile + ~1px gutter each side → ~2px between adjacent tiles
const ROW_H = CELL; // row height, px (compact)
const COL_W = CELL; // data column width, px
const LABEL_W = 120; // frozen gene-label column width, px

/**
 * Sequential status ramp in the orange range (darker = more signal), plus a
 * distinct mid-gray for "assayed but null" so it reads as measured-yet-empty.
 * `none` is essentially white (barely off-white) so gaps recede and the sparse
 * signal stands out; the gray of `assayed_null` is clearly darker than `none`.
 */
const STATUS_META: Record<
  CellStatus,
  { fill: string; border: string; label: string }
> = {
  significant: { fill: "#c2410b", border: "#9a3412", label: "Significant" },
  data: { fill: "#fdba74", border: "#fb923c", label: "Data, not significant" },
  assayed_null: { fill: "#9ca3af", border: "#8b909b", label: "Assayed, null result" },
  none: { fill: "#fcfcfd", border: "#eef0f2", label: "No data" },
};

/**
 * A single status tile — a small filled square. Shared between the heatmap
 * cells and the page legend so the two always render identically. `aria-label`
 * carries the meaning since the visual is color-only.
 */
export function StatusSwatch({
  status,
  size = TILE,
}: {
  status: CellStatus;
  size?: number;
}) {
  const m = STATUS_META[status];
  return (
    <span
      role="img"
      aria-label={m.label}
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: 2,
        background: m.fill,
        border: `1px solid ${m.border}`,
        boxSizing: "border-box",
        verticalAlign: "middle",
      }}
    />
  );
}

function significantModalityCount(g: MatrixGeneRow): number {
  let n = 0;
  for (const c of Object.values(g.cells)) {
    if (c.status === "significant") n++;
  }
  return n;
}

// Mirrors the API's own comparator: case-insensitive A→Z, null/empty last,
// ties broken by centralGeneId.
function bySymbol(a: MatrixGeneRow, b: MatrixGeneRow): number {
  const as = a.humanSymbol || "";
  const bs = b.humanSymbol || "";
  if (!as && !bs) return a.centralGeneId - b.centralGeneId;
  if (!as) return 1;
  if (!bs) return -1;
  return as.localeCompare(bs, "en", { sensitivity: "base" });
}

function cellTitle(gene: string, label: string, cell: MatrixCell): string {
  const meaning = STATUS_META[cell.status].label;
  if (cell.status === "none") return `${gene} · ${label}: no data`;
  const tables = cell.tableNames.length
    ? ` — ${cell.tableNames.join(", ")}`
    : "";
  const noun = cell.status === "assayed_null" ? "assayed" : "row";
  return `${gene} · ${label}: ${meaning} (${cell.count} ${noun}${
    cell.count === 1 ? "" : "s"
  })${tables}`;
}

export default function CollatedMatrix({
  modalities,
  genes,
}: {
  modalities: MatrixModalityColumn[];
  genes: MatrixGeneRow[];
}) {
  const [sortMode, setSortMode] = useState<SortMode>("symbol");

  const sortedGenes = useMemo(() => {
    const rows = [...genes];
    if (sortMode === "sig") {
      rows.sort(
        (a, b) =>
          significantModalityCount(b) - significantModalityCount(a) ||
          bySymbol(a, b)
      );
    } else {
      rows.sort(bySymbol);
    }
    return rows;
  }, [genes, sortMode]);

  const sortBtn = (mode: SortMode, label: string) => {
    const active = sortMode === mode;
    return (
      <button
        type="button"
        onClick={() => setSortMode(mode)}
        aria-pressed={active}
        style={{
          padding: "4px 10px",
          background: active ? "#e5e7eb" : "#ffffff",
          border: "1px solid #d1d5db",
          color: "#1f2937",
          borderRadius: 6,
          cursor: active ? "default" : "pointer",
          fontSize: 13,
          fontWeight: active ? 700 : 500,
        }}
      >
        {label}
      </button>
    );
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
          marginBottom: 10,
        }}
      >
        <div style={{ fontSize: 13, color: "#6b7280" }}>
          {sortedGenes.length.toLocaleString()} perturbed genes ×{" "}
          {modalities.length} modalities
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, color: "#374151", fontWeight: 600 }}>
            Sort rows:
          </span>
          {sortBtn("symbol", "Gene A→Z")}
          {sortBtn("sig", "Most significant")}
        </div>
      </div>

      <div
        style={{
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          overflow: "hidden",
        }}
      >
        <DoubleScrollX maxHeight={MATRIX_MAX_HEIGHT}>
          <table
            style={{
              borderCollapse: "separate",
              borderSpacing: 0,
              width: "auto",
              tableLayout: "fixed",
              WebkitTextSizeAdjust: "100%",
            }}
          >
            <thead>
              <tr>
                <th
                  scope="col"
                  style={{
                    position: "sticky",
                    top: 0,
                    left: 0,
                    zIndex: 3,
                    background: "#f9fafb",
                    textAlign: "right",
                    verticalAlign: "bottom",
                    fontWeight: 600,
                    fontSize: 12,
                    color: "#6b7280",
                    padding: "0 8px 6px",
                    width: LABEL_W,
                    minWidth: LABEL_W,
                    borderBottom: "1px solid #e5e7eb",
                    borderRight: "1px solid #e5e7eb",
                    whiteSpace: "nowrap",
                  }}
                >
                  Gene
                </th>
                {modalities.map((m) => (
                  <th
                    key={m.key}
                    scope="col"
                    title={m.isEmpty ? `${m.label} (no data yet)` : m.label}
                    style={{
                      position: "sticky",
                      top: 0,
                      zIndex: 2,
                      background: "#f9fafb",
                      verticalAlign: "bottom",
                      padding: "6px 0",
                      width: COL_W,
                      minWidth: COL_W,
                      borderBottom: "1px solid #e5e7eb",
                    }}
                  >
                    <div
                      style={{
                        writingMode: "vertical-rl",
                        transform: "rotate(180deg)",
                        margin: "0 auto",
                        fontSize: 12,
                        fontWeight: 600,
                        color: m.isEmpty ? "#9ca3af" : "#374151",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {m.label}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedGenes.map((g, i) => {
                const rowBg = i % 2 === 0 ? "#ffffff" : "#fafbfc";
                const gene = g.humanSymbol ?? `#${g.centralGeneId}`;
                return (
                  <tr key={g.centralGeneId} style={{ height: ROW_H }}>
                    <th
                      scope="row"
                      title={gene}
                      style={{
                        position: "sticky",
                        left: 0,
                        zIndex: 1,
                        background: rowBg,
                        textAlign: "right",
                        fontWeight: 500,
                        fontSize: 11,
                        color: g.humanSymbol ? "#1f2937" : "#9ca3af",
                        padding: "0 8px",
                        width: LABEL_W,
                        minWidth: LABEL_W,
                        maxWidth: LABEL_W,
                        borderRight: "1px solid #e5e7eb",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {gene}
                    </th>
                    {modalities.map((m) => {
                      const cell =
                        g.cells[m.key] ??
                        ({ status: "none", count: 0, tableNames: [] } as MatrixCell);
                      return (
                        <td
                          key={m.key}
                          title={cellTitle(gene, m.label, cell)}
                          style={{
                            background: rowBg,
                            textAlign: "center",
                            padding: 0,
                            width: COL_W,
                            minWidth: COL_W,
                            height: ROW_H,
                            lineHeight: 0,
                          }}
                        >
                          <StatusSwatch status={cell.status} />
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </DoubleScrollX>
      </div>
    </div>
  );
}
