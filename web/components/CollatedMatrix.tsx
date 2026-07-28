import { useMemo, useState } from "react";
import DoubleScrollX from "@/components/DoubleScrollX";
import {
  isPvalueCell,
  type CellStatus,
  type MatrixColumn,
  type MatrixGeneRow,
  type MatrixSection,
} from "@/lib/collated-matrix-types";

/**
 * CollatedMatrix — the perturbed-gene × modality "red table" (epic #220),
 * rendered as a compact heatmap. Rows are experimentally-perturbed genes;
 * columns come in two flavours (the #222 contract, `@/lib/collated-matrix-types`):
 *
 * - **status** columns (one per un-expanded modality): a small color-coded tile
 *   whose fill encodes a status glyph (significant / data / assayed-null / none).
 * - **pvalue** columns (an *expanded* section, e.g. RNA expression fanned out
 *   into one column per significant target gene): a yellow→orange→red tile whose
 *   fill encodes `-log10(p)` (red = most significant).
 *
 * Sections group the columns; the header is two-tier — a section band over the
 * per-column labels. A DataTable config can't express this (sticky header +
 * frozen first column), so this is a purpose-built component. Horizontal scroll
 * + sticky axes are handled by a bounded-height DoubleScrollX.
 */

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
const SECTION_H = 24; // height of the top section-band header row, px

// p < 0.05 as a -log10(p) threshold — the bar for counting a cell "significant"
// in the row-sort score and, for a status cell, what the API already applied.
const SIG_NEG_LOG_P = 1.30103;

/**
 * Status ramp for un-expanded modality tiles. Orange for signal (darker = more),
 * a distinct mid-gray for "assayed but null", near-white for "no data" so gaps
 * recede. Shared with the page legend so the two render identically.
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

// ColorBrewer "YlOrRd" anchors — the p-value heatmap ramp. Position ∈ [0,1].
const YLORRD: Array<[number, [number, number, number]]> = [
  [0.0, [255, 255, 204]],
  [0.25, [254, 217, 118]],
  [0.5, [253, 141, 60]],
  [0.75, [240, 59, 32]],
  [1.0, [189, 0, 38]],
];

function lerp(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t);
}

/**
 * Map a clamped `-log10(p)` (the API already clamps to [1, 20]) onto the YlOrRd
 * ramp. 1 → palest yellow, 20 → deep red. Exported so the page legend paints the
 * exact same gradient.
 */
export function pColor(negLogP: number): string {
  const t = (Math.min(Math.max(negLogP, 1), 20) - 1) / 19;
  let lo = YLORRD[0];
  let hi = YLORRD[YLORRD.length - 1];
  for (let i = 0; i < YLORRD.length - 1; i++) {
    if (t >= YLORRD[i][0] && t <= YLORRD[i + 1][0]) {
      lo = YLORRD[i];
      hi = YLORRD[i + 1];
      break;
    }
  }
  const span = hi[0] - lo[0] || 1;
  const local = (t - lo[0]) / span;
  const [r, g, b] = [0, 1, 2].map((k) => lerp(lo[1][k], hi[1][k], local));
  return `rgb(${r}, ${g}, ${b})`;
}

/** A small filled square tile. */
function Tile({
  fill,
  border,
  label,
  size = TILE,
}: {
  fill: string;
  border: string;
  label: string;
  size?: number;
}) {
  return (
    <span
      role="img"
      aria-label={label}
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: 2,
        background: fill,
        border: `1px solid ${border}`,
        boxSizing: "border-box",
        verticalAlign: "middle",
      }}
    />
  );
}

/** Status tile — reused by the page legend. */
export function StatusSwatch({
  status,
  size = TILE,
}: {
  status: CellStatus;
  size?: number;
}) {
  const m = STATUS_META[status];
  return <Tile fill={m.fill} border={m.border} label={m.label} size={size} />;
}

/** p-value tile — reused by the page legend ramp. */
export function PvalueSwatch({
  negLogP,
  size = TILE,
}: {
  negLogP: number;
  size?: number;
}) {
  return (
    <Tile
      fill={pColor(negLogP)}
      border="rgba(0,0,0,0.12)"
      label={`-log10(p) ≈ ${negLogP}`}
      size={size}
    />
  );
}

const NO_DATA_TILE = (
  <Tile fill={STATUS_META.none.fill} border={STATUS_META.none.border} label="No data" />
);

// Case-insensitive A→Z, null/empty last, ties by id — mirrors the API.
function bySymbol(a: MatrixGeneRow, b: MatrixGeneRow): number {
  const as = a.humanSymbol || "";
  const bs = b.humanSymbol || "";
  if (!as && !bs) return a.centralGeneId - b.centralGeneId;
  if (!as) return 1;
  if (!bs) return -1;
  return as.localeCompare(bs, "en", { sensitivity: "base" });
}

// Count of "significant" cells across a gene's row: a significant status cell,
// or a p-value cell at p < 0.05. Only present cells are iterated.
function significanceScore(g: MatrixGeneRow): number {
  let n = 0;
  for (const cell of Object.values(g.cells)) {
    if (isPvalueCell(cell)) {
      if (cell.negLogP >= SIG_NEG_LOG_P) n++;
    } else if (cell.status === "significant") {
      n++;
    }
  }
  return n;
}

function pApprox(negLogP: number): string {
  if (negLogP >= 20) return "p ≤ 1e-20";
  if (negLogP <= 1) return "p ≥ 0.1";
  return `p ≈ ${Math.pow(10, -negLogP).toExponential(1)}`;
}

function cellTitle(
  gene: string,
  column: MatrixColumn,
  cell: MatrixGeneRow["cells"][string] | undefined
): string {
  if (column.kind === "pvalue") {
    if (cell && isPvalueCell(cell)) {
      return `${gene} · ${column.label}: ${pApprox(cell.negLogP)} (-log10 ${cell.negLogP})`;
    }
    return `${gene} · ${column.label}: no data`;
  }
  const status: CellStatus =
    cell && !isPvalueCell(cell) ? cell.status : "none";
  const meaning = STATUS_META[status].label;
  if (status === "none") return `${gene} · ${column.label}: no data`;
  const count = cell && !isPvalueCell(cell) ? cell.count : 0;
  const tables =
    cell && !isPvalueCell(cell) && cell.tableNames.length
      ? ` — ${cell.tableNames.join(", ")}`
      : "";
  const noun = status === "assayed_null" ? "assayed" : "row";
  return `${gene} · ${column.label}: ${meaning} (${count} ${noun}${
    count === 1 ? "" : "s"
  })${tables}`;
}

export default function CollatedMatrix({
  sections,
  columns,
  genes,
}: {
  sections: MatrixSection[];
  columns: MatrixColumn[];
  genes: MatrixGeneRow[];
}) {
  const [sortMode, setSortMode] = useState<SortMode>("symbol");

  const sortedGenes = useMemo(() => {
    const rows = [...genes];
    if (sortMode === "sig") {
      rows.sort(
        (a, b) => significanceScore(b) - significanceScore(a) || bySymbol(a, b)
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

  const expandedCols = columns.filter((c) => c.kind === "pvalue").length;

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
          {columns.length.toLocaleString()} columns
          {expandedCols > 0 &&
            ` (${expandedCols.toLocaleString()} expanded RNA-expression targets)`}
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
              {/* Row 1 — section band. The frozen corner spans both header rows. */}
              <tr>
                <th
                  scope="col"
                  rowSpan={2}
                  style={{
                    position: "sticky",
                    top: 0,
                    left: 0,
                    zIndex: 5,
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
                {sections.map((s) => (
                  <th
                    key={s.key}
                    scope="colgroup"
                    colSpan={s.span}
                    title={s.label}
                    style={{
                      position: "sticky",
                      top: 0,
                      zIndex: 4,
                      height: SECTION_H,
                      background: "#f3f4f6",
                      color: s.isEmpty ? "#9ca3af" : "#374151",
                      fontWeight: 700,
                      fontSize: 12,
                      padding: 0,
                      textAlign: "left",
                      whiteSpace: "nowrap",
                      borderBottom: "1px solid #e5e7eb",
                      borderLeft: "1px solid #e5e7eb",
                    }}
                  >
                    {/* Expanded sections span thousands of px; a sticky-left
                        label rides the viewport so it stays visible as you scroll
                        across the section. Single-column status sections are too
                        narrow (17px) for horizontal text — their name is carried
                        by the vertical per-column header below, band left blank. */}
                    {s.kind === "expanded" ? (
                      <div
                        style={{
                          position: "sticky",
                          left: LABEL_W,
                          padding: "0 8px",
                          display: "inline-block",
                          maxWidth: "100%",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {s.label}
                      </div>
                    ) : (
                      ""
                    )}
                  </th>
                ))}
              </tr>
              {/* Row 2 — per-column vertical labels. */}
              <tr>
                {columns.map((c) => (
                  <th
                    key={c.key}
                    scope="col"
                    title={c.label}
                    style={{
                      position: "sticky",
                      top: SECTION_H,
                      zIndex: 4,
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
                        color: "#374151",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {c.label}
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
                        zIndex: 2,
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
                    {columns.map((c) => {
                      const cell = g.cells[c.key];
                      let tile;
                      if (c.kind === "pvalue") {
                        tile =
                          cell && isPvalueCell(cell) ? (
                            <PvalueSwatch negLogP={cell.negLogP} />
                          ) : (
                            NO_DATA_TILE
                          );
                      } else {
                        const status: CellStatus =
                          cell && !isPvalueCell(cell) ? cell.status : "none";
                        tile = <StatusSwatch status={status} />;
                      }
                      return (
                        <td
                          key={c.key}
                          title={cellTitle(gene, c, cell)}
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
                          {tile}
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
