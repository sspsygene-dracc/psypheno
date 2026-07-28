import { useMemo } from "react";
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
 * - **status** columns (one per un-expanded modality): a color-coded tile whose
 *   fill encodes a status glyph (significant / data / assayed-null / none).
 * - **pvalue** columns (an *expanded* section — RNA expression, perturb-seq,
 *   perturb-FISH — fanned out into one column per significant target gene,
 *   grouped by source dataset): a yellow→orange→red tile encoding `-log10(p)`.
 *
 * The header is two-tier: a band row ("experiment type · author-year", one cell
 * per source dataset) → per-column gene labels. A DataTable can't express this
 * (sticky multi-row header + frozen first column), so it's purpose-built. It
 * scrolls in a single native bounded-height container — no JS scroll-syncing —
 * so horizontal trackpad/scrollbar scrolling stays smooth; the header sticks to
 * the top and the gene column stays frozen at the left.
 */

const MATRIX_MAX_HEIGHT = "72vh";
const TILE = 15; // color tile edge, px
const CELL = 17; // tile + ~1px gutter each side → ~2px between adjacent tiles
const ROW_H = CELL;
const COL_W = CELL;
const LABEL_W = 120; // frozen gene-label column width, px
const BAND_H = 22; // header band row ("experiment · author") height, px

// p < 0.05 as a -log10(p) value (informational; the API already applied FDR).
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

/** Map a clamped `-log10(p)` (API clamps to [1,20]) onto the YlOrRd ramp. */
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

// Fill / border / a11y-label for one grid cell. Painted directly on the `<td>`
// (no child node) — see the cell render below — so the ~42k-cell grid is ~42k
// DOM nodes instead of ~84k.
function cellVisual(
  column: MatrixColumn,
  cell: MatrixGeneRow["cells"][string] | undefined
): { fill: string; border: string; label: string } {
  if (column.kind === "pvalue") {
    if (cell && isPvalueCell(cell)) {
      return {
        fill: pColor(cell.negLogP),
        border: "rgba(0,0,0,0.12)",
        label: `-log10(p) ≈ ${cell.negLogP}`,
      };
    }
    return { ...STATUS_META.none, label: "No data" };
  }
  const status: CellStatus = cell && !isPvalueCell(cell) ? cell.status : "none";
  const m = STATUS_META[status];
  return { fill: m.fill, border: m.border, label: m.label };
}

function pApprox(negLogP: number): string {
  if (negLogP >= 20) return "p ≤ 1e-20";
  if (negLogP <= 1) return "p ≥ 0.1";
  return `p ≈ ${Math.pow(10, -negLogP).toExponential(1)}`;
}

// Rich hover text for one cell (native `title`), so every square names its
// perturbed gene, measured target, dataset, and value.
function cellTitle(
  gene: string,
  column: MatrixColumn,
  cell: MatrixGeneRow["cells"][string] | undefined
): string {
  if (column.kind === "pvalue") {
    const metric = column.section === "perturb_fish" ? "qval" : "p";
    if (cell && isPvalueCell(cell)) {
      return (
        `${gene} (perturbed) × ${column.label} (measured) — ${column.sourceLabel}\n` +
        `${pApprox(cell.negLogP).replace("p", metric)}  (-log10 = ${cell.negLogP})`
      );
    }
    return `${gene} × ${column.label} — ${column.sourceLabel}: no data`;
  }
  const status: CellStatus =
    cell && !isPvalueCell(cell) ? cell.status : "none";
  const meaning = STATUS_META[status].label;
  if (status === "none") return `${gene} × ${column.label}: no data`;
  const count = cell && !isPvalueCell(cell) ? cell.count : 0;
  const tables =
    cell && !isPvalueCell(cell) && cell.tableNames.length
      ? ` — ${cell.tableNames.join(", ")}`
      : "";
  const noun = status === "assayed_null" ? "assayed" : "row";
  return `${gene} × ${column.label}: ${meaning} (${count} ${noun}${
    count === 1 ? "" : "s"
  })${tables}`;
}

// Contiguous run of columns sharing a dataset (or a single status column) — the
// row-2 dataset band. Columns arrive grouped by dataset from the API.
interface BandGroup {
  gkey: string;
  kind: "pvalue" | "status";
  /** "RNA expression · Gordon 2026" for an expanded dataset; "" for a status column. */
  bandLabel: string;
  tooltip: string | null;
  span: number;
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
  const sectionLabel = useMemo(
    () => new Map(sections.map((s) => [s.key, s.label])),
    [sections]
  );

  // One band cell per contiguous run of columns sharing a dataset (or a single
  // status column). The band shows "experiment type · author-year" on one line —
  // a single header tier that scrolls with its columns (no horizontal pinning),
  // which is what keeps horizontal scrolling smooth across browsers.
  const datasetGroups = useMemo<BandGroup[]>(() => {
    const groups: BandGroup[] = [];
    for (const c of columns) {
      const gkey =
        c.kind === "pvalue" ? `${c.section}|${c.sourceTable}` : `status|${c.key}`;
      const last = groups[groups.length - 1];
      if (last && last.gkey === gkey) {
        last.span++;
        continue;
      }
      const modality = sectionLabel.get(c.section) ?? c.section;
      groups.push({
        gkey,
        kind: c.kind,
        bandLabel: c.kind === "pvalue" ? `${modality} · ${c.sourceLabel}` : "",
        tooltip:
          c.kind === "pvalue"
            ? [c.sourceMediumLabel ?? c.sourceLabel, c.sourceCitation]
                .filter(Boolean)
                .join(" — ")
            : null,
        span: 1,
      });
    }
    return groups;
  }, [columns, sectionLabel]);

  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        overflow: "hidden",
      }}
    >
      <div
        className="matrix-scroll"
        style={{ overflow: "auto", maxHeight: MATRIX_MAX_HEIGHT }}
      >
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
            {/* Row 1 — band: "experiment type · author-year", one cell per dataset
                group. Sticky to the top (stays put on vertical scroll) but NOT
                horizontally pinned, so it just scrolls with its columns — no nested
                sticky-left, which is what flickered during horizontal scroll. */}
            <tr>
              <th
                scope="col"
                rowSpan={2}
                title="Rows are experimentally perturbed SSPsyGene target genes — one row per perturbed gene. Hover any square for its value."
                style={{
                  position: "sticky",
                  top: 0,
                  left: 0,
                  zIndex: 6,
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
              {datasetGroups.map((g) => (
                <th
                  key={g.gkey}
                  scope="colgroup"
                  colSpan={g.span}
                  title={g.tooltip ?? undefined}
                  style={{
                    position: "sticky",
                    top: 0,
                    zIndex: 5,
                    background: "#f3f4f6",
                    height: BAND_H,
                    textAlign: "left",
                    fontSize: 11,
                    fontWeight: 600,
                    color: "#374151",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    padding: "0 8px",
                    borderBottom: "1px solid #e5e7eb",
                    borderLeft: "1px solid #e5e7eb",
                  }}
                >
                  {g.bandLabel}
                </th>
              ))}
            </tr>
            {/* Row 2 — per-column vertical gene labels. */}
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  title={
                    c.kind === "pvalue"
                      ? `${c.label} — ${c.sourceLabel} (significant in ${c.nSigGroups} perturbations)`
                      : c.label
                  }
                  style={{
                    position: "sticky",
                    top: BAND_H,
                    zIndex: 5,
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
            {genes.map((g, i) => {
              const rowBg = i % 2 === 0 ? "#ffffff" : "#fafbfc";
              const gene = g.humanSymbol ?? `#${g.centralGeneId}`;
              return (
                <tr
                  key={g.centralGeneId}
                  style={{
                    height: ROW_H,
                    // Row stripe shows through each tile's 1px transparent border
                    // (the inter-tile gap), so it lives on the <tr>, not the <td>.
                    background: rowBg,
                    // Skip layout+paint for off-screen rows — only the ~30 visible
                    // rows are painted per frame instead of all ~240, which is what
                    // makes scrolling a 42k-cell grid smooth. `contain-intrinsic-height`
                    // (not the `-size` shorthand) reserves only the height, leaving
                    // the fixed table layout to own each column's width.
                    contentVisibility: "auto",
                    containIntrinsicHeight: `${ROW_H}px`,
                  }}
                >
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
                    const { fill, border, label } = cellVisual(c, cell);
                    // The tile is painted directly on the <td> (no child span):
                    // a 1px transparent border is the inter-tile gap (row stripe
                    // shows through), a padding-box layer draws the tile's 1px
                    // border, and a content-box layer draws the fill.
                    return (
                      <td
                        key={c.key}
                        role="img"
                        aria-label={label}
                        title={cellTitle(gene, c, cell)}
                        style={{
                          boxSizing: "border-box",
                          width: COL_W,
                          minWidth: COL_W,
                          height: ROW_H,
                          padding: 1,
                          border: "1px solid transparent",
                          borderRadius: 2,
                          background: `linear-gradient(${fill}, ${fill}) content-box, linear-gradient(${border}, ${border}) padding-box`,
                        }}
                      />
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
