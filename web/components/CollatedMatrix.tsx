import { useEffect, useMemo, useRef, useState } from "react";
import { EyeOff } from "lucide-react";
import {
  type MatrixCell,
  type MatrixColumn,
  type MatrixGeneRow,
  type MatrixSection,
} from "@/lib/collated-matrix-types";
import { scaleFor } from "@/lib/matrix-color-scales";
import {
  buildColorGrid,
  cellAt,
  drawCells,
  COL_W,
  ROW_H,
  type MetricDomains,
} from "@/lib/matrix-canvas";

export type { MetricDomains };

/**
 * CollatedMatrix — the perturbed-gene × modality "red table" (epic #220),
 * rendered as a compact heatmap. Rows are experimentally-perturbed genes; every
 * column is a value sub-column of an expanded dataset, colored through the
 * column's `metric` color scale.
 *
 * Rendering (#213): the cell field is drawn on a single `<canvas>` — one styled
 * `<td>` per cell doesn't scroll once there are tens of thousands. The DOM keeps
 * only the parts that need text / links / hit targets: the pinned header (dataset
 * bands + rotated column labels), the frozen gene column, and (elsewhere) the
 * legends. The matrix is a fixed-height panel — both scrollbars live inside it,
 * the header stays pinned, and the surrounding page doesn't scroll it — laid out
 * as four regions —
 *
 *     corner  │ header       (pinned top,  translateX ← body scrollLeft)
 *     ────────┼──────────
 *     labels  │ body/canvas  (the only real scroller; x & y)
 *     (pinned left, translateY ← body scrollTop)
 *
 * — where the body is the single scroll source of truth and the header + gene
 * column are slaved to its offset. Header/labels are windowed to their visible
 * span so their DOM stays small at any column count. A click selects a cell and
 * opens a value popover (replacing the per-cell hover title canvas can't carry).
 *
 * Header modes: with columns grouped by dataset (`bandsVisible`) a band row
 * ("experiment · author-year", with a hide control) sits above per-column labels.
 * When columns are clustered (`!bandsVisible`) the grouping is gone, so the
 * dataset folds into each column's single vertical label.
 */

const LABEL_W = 120; // frozen gene-label column width, px
const BAND_H = 34; // header band row — tall enough for a wrapped dataset heading
const LABEL_STRIP_H = 150; // vertical column-label strip height
const COL_OVERSCAN = 12; // extra columns rendered each side of the header window
const ROW_OVERSCAN = 24; // extra gene labels rendered each side of the row window
const DEFAULT_PANEL_H = "76vh"; // fixed panel height: both scrollbars live inside it

const ROW_STRIPE_EVEN = "#ffffff";
const ROW_STRIPE_ODD = "#fafbfc";

function fmtValue(metric: string, value: number): string {
  const label = scaleFor(metric).label;
  if (metric === "neglog_p" || metric === "neglog_q") {
    const p =
      value >= 20 ? "≤ 1e-20" : value <= 1 ? "≥ 0.1" : `≈ ${Math.pow(10, -value).toExponential(1)}`;
    const stat = metric === "neglog_q" ? "FDR" : "p";
    return `${label} = ${value} (${stat} ${p})`;
  }
  return `${label} = ${value}`;
}

interface BandGroup {
  gkey: string;
  bandLabel: string;
  sourceTable: string;
  tooltip: string | null;
  span: number;
  startCol: number;
}

const VLABEL_STYLE = {
  writingMode: "vertical-rl",
  transform: "rotate(180deg)",
  fontSize: 12,
  fontWeight: 600,
  color: "#374151",
  whiteSpace: "nowrap",
} as const;

/** One column's vertical label; `datasetText` (when set) prefixes the dataset. */
function ColumnLabel({
  column,
  datasetText,
}: {
  column: MatrixColumn;
  datasetText: string | null;
}) {
  return (
    <div style={VLABEL_STYLE}>
      {datasetText && (
        <>
          <a
            className="matrix-link"
            href={`/full-datasets?open=${encodeURIComponent(column.sourceTable)}`}
          >
            {datasetText}
          </a>
          {" · "}
        </>
      )}
      {column.columnIsGene ? (
        <a
          className="matrix-link"
          href={`/?target=${encodeURIComponent(column.label)}`}
        >
          {column.label}
        </a>
      ) : (
        column.label
      )}
    </div>
  );
}

const VISUALLY_HIDDEN = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
  border: 0,
} as const;

export default function CollatedMatrix({
  sections,
  columns,
  genes,
  metricDomains,
  bandsVisible,
  onToggleHide,
  panelHeight = DEFAULT_PANEL_H,
}: {
  sections: MatrixSection[];
  columns: MatrixColumn[];
  genes: MatrixGeneRow[];
  metricDomains: MetricDomains;
  /** When true, columns are grouped by dataset and a band row is shown. */
  bandsVisible: boolean;
  onToggleHide: (sourceTable: string) => void;
  /**
   * Fixed panel height. Both the vertical and horizontal scrollbars live inside
   * this panel and the header stays pinned; the surrounding page doesn't scroll
   * the matrix.
   */
  panelHeight?: number | string;
}) {
  const nRows = genes.length;
  const nCols = columns.length;
  const HEADER_H = (bandsVisible ? BAND_H : 0) + LABEL_STRIP_H;

  const sectionLabel = useMemo(
    () => new Map(sections.map((s) => [s.key, s.label])),
    [sections]
  );

  const bandLayout = useMemo<BandGroup[]>(() => {
    const groups: BandGroup[] = [];
    columns.forEach((c, j) => {
      const gkey = `${c.section}|${c.sourceTable}`;
      const last = groups[groups.length - 1];
      if (last && last.gkey === gkey) {
        last.span++;
        return;
      }
      const modality = sectionLabel.get(c.section) ?? c.section;
      groups.push({
        gkey,
        bandLabel: `${modality} · ${c.sourceLabel}`,
        sourceTable: c.sourceTable,
        tooltip: [c.sourceMediumLabel ?? c.sourceLabel, c.sourceCitation]
          .filter(Boolean)
          .join(" — "),
        span: 1,
        startCol: j,
      });
    });
    return groups;
  }, [columns, sectionLabel]);

  // Every cell's color, precomputed once per data/order change (packed RGB +
  // present-mask). Scrolling never recomputes a color.
  const colorGrid = useMemo(
    () => buildColorGrid(genes, columns, metricDomains),
    [genes, columns, metricDomains]
  );

  const rootRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const headerInnerRef = useRef<HTMLDivElement>(null);
  const rowLabelsInnerRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const dprRef = useRef(1);

  // Viewport client size of the body scroller (drives canvas backing store).
  const [size, setSize] = useState({ w: 0, h: 0 });
  // Visible spans of columns / rows for windowing the DOM header + gene column.
  const [colWindow, setColWindow] = useState({ start: 0, end: 0 });
  const [rowWindow, setRowWindow] = useState({ start: 0, end: 0 });
  const [selected, setSelected] = useState<{ row: number; col: number } | null>(null);

  // Reset any selection when the data / ordering changes (indices would drift).
  useEffect(() => {
    setSelected(null);
  }, [columns, genes]);

  // --- draw + popover positioning kept in refs so listeners never go stale. ---
  const drawRef = useRef<() => void>(() => {});
  drawRef.current = () => {
    const el = scrollRef.current;
    const canvas = canvasRef.current;
    if (!el || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    drawCells(ctx, {
      grid: colorGrid,
      scrollLeft: el.scrollLeft,
      scrollTop: el.scrollTop,
      viewW: el.clientWidth,
      viewH: el.clientHeight,
      dpr: dprRef.current,
      selected,
    });
  };

  const positionRef = useRef<(sl: number, st: number, vw: number, vh: number) => void>(
    () => {}
  );
  positionRef.current = (sl, st, vw, vh) => {
    const pop = popoverRef.current;
    if (!pop) return;
    if (!selected || !genes[selected.row] || !columns[selected.col]) {
      pop.style.display = "none";
      return;
    }
    const cellX = selected.col * COL_W - sl;
    const cellY = selected.row * ROW_H - st;
    if (cellX < -COL_W || cellX > vw || cellY < -ROW_H || cellY > vh) {
      pop.style.display = "none";
      return;
    }
    pop.style.display = "block";
    const rootW = rootRef.current?.clientWidth ?? vw + LABEL_W;
    const popW = pop.offsetWidth || 220;
    let left = LABEL_W + cellX + COL_W + 6;
    if (left + popW > rootW - 4) left = LABEL_W + cellX - popW - 6;
    if (left < 4) left = 4;
    pop.style.left = `${left}px`;
    pop.style.top = `${HEADER_H + cellY + ROW_H}px`;
  };

  // Body scroll: imperatively slave the header/gene-column/canvas to the offset
  // (rAF-coalesced), redraw, reposition the popover, and update the DOM windows
  // only when the visible span actually shifts.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    let raf = 0;
    const frame = () => {
      raf = 0;
      const sl = el.scrollLeft;
      const st = el.scrollTop;
      const vw = el.clientWidth;
      const vh = el.clientHeight;
      if (headerInnerRef.current)
        headerInnerRef.current.style.transform = `translateX(${-sl}px)`;
      if (rowLabelsInnerRef.current)
        rowLabelsInnerRef.current.style.transform = `translateY(${-st}px)`;
      if (canvasRef.current)
        canvasRef.current.style.transform = `translate(${sl}px, ${st}px)`;
      drawRef.current();
      positionRef.current(sl, st, vw, vh);
      const cStart = Math.max(0, Math.floor(sl / COL_W) - COL_OVERSCAN);
      const cEnd = Math.min(nCols, Math.ceil((sl + vw) / COL_W) + COL_OVERSCAN);
      const rStart = Math.max(0, Math.floor(st / ROW_H) - ROW_OVERSCAN);
      const rEnd = Math.min(nRows, Math.ceil((st + vh) / ROW_H) + ROW_OVERSCAN);
      setColWindow((p) => (p.start === cStart && p.end === cEnd ? p : { start: cStart, end: cEnd }));
      setRowWindow((p) => (p.start === rStart && p.end === rEnd ? p : { start: rStart, end: rEnd }));
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(frame);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    frame(); // initial sync
    return () => {
      if (raf) cancelAnimationFrame(raf);
      el.removeEventListener("scroll", onScroll);
    };
  }, [nRows, nCols]);

  // Track the body's client size (canvas backing store) via ResizeObserver.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const update = () =>
      setSize((p) =>
        p.w === el.clientWidth && p.h === el.clientHeight
          ? p
          : { w: el.clientWidth, h: el.clientHeight }
      );
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    window.addEventListener("resize", update);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", update);
    };
  }, []);

  // Size the canvas backing store (DPR-scaled) and redraw when size/grid change.
  useEffect(() => {
    const el = scrollRef.current;
    const canvas = canvasRef.current;
    if (!el || !canvas) return;
    const dpr = window.devicePixelRatio || 1;
    dprRef.current = dpr;
    const vw = el.clientWidth;
    const vh = el.clientHeight;
    canvas.style.width = `${vw}px`;
    canvas.style.height = `${vh}px`;
    canvas.width = Math.round(vw * dpr);
    canvas.height = Math.round(vh * dpr);
    drawRef.current();
  }, [size, colorGrid, HEADER_H]);

  // Redraw + reposition the popover when the selection changes.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    drawRef.current();
    positionRef.current(el.scrollLeft, el.scrollTop, el.clientWidth, el.clientHeight);
  }, [selected]);

  // Dismiss the popover on Escape or an outside mousedown.
  useEffect(() => {
    if (!selected) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
    };
    const onDown = (e: MouseEvent) => {
      const canvas = canvasRef.current;
      const pop = popoverRef.current;
      const t = e.target as Node;
      if ((canvas && canvas.contains(t)) || (pop && pop.contains(t))) return;
      setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [selected]);

  const onCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const el = scrollRef.current;
    const canvas = canvasRef.current;
    if (!el || !canvas) return;
    const rect = canvas.getBoundingClientRect();
    const hit = cellAt(
      e.clientX - rect.left,
      e.clientY - rect.top,
      el.scrollLeft,
      el.scrollTop,
      nRows,
      nCols
    );
    setSelected((prev) =>
      hit && prev && prev.row === hit.row && prev.col === hit.col ? null : hit
    );
  };

  // Selection details for the popover + aria-live text.
  const sel =
    selected && genes[selected.row] && columns[selected.col]
      ? { gene: genes[selected.row], col: columns[selected.col] }
      : null;
  const selCell: MatrixCell | undefined = sel ? sel.gene.cells[sel.col.key] : undefined;
  const selGeneName = sel ? sel.gene.humanSymbol ?? `#${sel.gene.centralGeneId}` : "";
  const selValueText = sel
    ? selCell
      ? fmtValue(sel.col.metric, selCell.value)
      : "No data"
    : "";

  const labelStripTop = bandsVisible ? BAND_H : 0;

  return (
    <div
      ref={rootRef}
      style={{
        position: "relative",
        height: panelHeight,
        display: "grid",
        gridTemplateColumns: `${LABEL_W}px 1fr`,
        gridTemplateRows: `${HEADER_H}px 1fr`,
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        overflow: "hidden",
        background: "#ffffff",
      }}
    >
      {/* Corner (static). */}
      <div
        title="Rows are experimentally perturbed SSPsyGene target genes — one row per perturbed gene. Click any square for its value."
        style={{
          gridColumn: 1,
          gridRow: 1,
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "flex-end",
          background: "#f9fafb",
          fontWeight: 600,
          fontSize: 12,
          color: "#6b7280",
          padding: "0 8px 6px",
          lineHeight: 1.2,
          textAlign: "right",
          borderRight: "1px solid #e5e7eb",
          borderBottom: "1px solid #e5e7eb",
          zIndex: 3,
        }}
      >
        Perturbed gene ↓
      </div>

      {/* Header (pinned top; slaved horizontally to the body scroll). */}
      <div
        style={{
          gridColumn: 2,
          gridRow: 1,
          overflow: "hidden",
          background: "#f9fafb",
          borderBottom: "1px solid #e5e7eb",
          position: "relative",
        }}
      >
        <div
          ref={headerInnerRef}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: nCols * COL_W,
            height: HEADER_H,
            willChange: "transform",
          }}
        >
          {/* Dataset bands (grouped mode only). */}
          {bandsVisible &&
            bandLayout
              .filter(
                (g) => g.startCol < colWindow.end && g.startCol + g.span > colWindow.start
              )
              .map((g) => (
                <div
                  key={g.gkey}
                  title={g.tooltip ?? undefined}
                  style={{
                    position: "absolute",
                    left: g.startCol * COL_W,
                    top: 0,
                    width: g.span * COL_W,
                    height: BAND_H,
                    background: "#f3f4f6",
                    borderLeft: "1px solid #e5e7eb",
                    borderBottom: "1px solid #e5e7eb",
                    boxSizing: "border-box",
                    padding: "3px 4px",
                    overflow: "hidden",
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 2,
                    fontSize: 11,
                    fontWeight: 600,
                    color: "#374151",
                  }}
                >
                  <a
                    className="matrix-link"
                    style={{ flex: 1, whiteSpace: "normal", lineHeight: 1.15 }}
                    href={`/full-datasets?open=${encodeURIComponent(g.sourceTable)}`}
                  >
                    {g.bandLabel}
                  </a>
                  <button
                    type="button"
                    aria-label={`Hide ${g.bandLabel}`}
                    title="Hide this dataset"
                    onClick={() => onToggleHide(g.sourceTable)}
                    style={{
                      flexShrink: 0,
                      display: "inline-flex",
                      padding: 1,
                      border: "none",
                      background: "transparent",
                      color: "#9ca3af",
                      cursor: "pointer",
                    }}
                  >
                    <EyeOff size={13} />
                  </button>
                </div>
              ))}

          {/* Per-column vertical labels (dataset folded in when clustered). */}
          {columns.slice(colWindow.start, colWindow.end).map((c, idx) => {
            const j = colWindow.start + idx;
            const modality = sectionLabel.get(c.section) ?? c.section;
            const datasetText = bandsVisible ? null : `${modality} · ${c.sourceLabel}`;
            return (
              <div
                key={c.key}
                title={
                  (bandsVisible ? "" : `${modality} · ${c.sourceLabel} — `) +
                  (c.columnIsGene
                    ? `${c.label} (significant in ${c.nSigGroups} perturbations)`
                    : c.label)
                }
                style={{
                  position: "absolute",
                  left: j * COL_W,
                  top: labelStripTop,
                  width: COL_W,
                  height: LABEL_STRIP_H,
                  overflow: "hidden",
                  display: "flex",
                  justifyContent: "center",
                  alignItems: "flex-end",
                  paddingBottom: 4,
                  boxSizing: "border-box",
                }}
              >
                <ColumnLabel column={c} datasetText={datasetText} />
              </div>
            );
          })}
        </div>
      </div>

      {/* Frozen gene column (pinned left; slaved vertically to the body scroll). */}
      <div
        style={{
          gridColumn: 1,
          gridRow: 2,
          overflow: "hidden",
          background: "#ffffff",
          borderRight: "1px solid #e5e7eb",
          position: "relative",
        }}
      >
        <div
          ref={rowLabelsInnerRef}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: LABEL_W,
            height: nRows * ROW_H,
            willChange: "transform",
          }}
        >
          {genes.slice(rowWindow.start, rowWindow.end).map((g, idx) => {
            const i = rowWindow.start + idx;
            const gene = g.humanSymbol ?? `#${g.centralGeneId}`;
            return (
              <div
                key={g.centralGeneId}
                title={gene}
                style={{
                  position: "absolute",
                  top: i * ROW_H,
                  left: 0,
                  width: LABEL_W,
                  height: ROW_H,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "flex-end",
                  padding: "0 8px",
                  boxSizing: "border-box",
                  background: i % 2 === 0 ? ROW_STRIPE_EVEN : ROW_STRIPE_ODD,
                  fontSize: 11,
                  fontWeight: 500,
                  color: g.humanSymbol ? "#1f2937" : "#9ca3af",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                }}
              >
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {g.humanSymbol ? (
                    <a
                      className="matrix-link"
                      href={`/?perturbed=${encodeURIComponent(g.humanSymbol)}`}
                    >
                      {gene}
                    </a>
                  ) : (
                    gene
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Body — the real scroller; the canvas draws the visible cell window. */}
      <div
        ref={scrollRef}
        style={{
          gridColumn: 2,
          gridRow: 2,
          overflow: "auto",
          position: "relative",
          background: "#ffffff",
        }}
      >
        <div style={{ width: nCols * COL_W, height: nRows * ROW_H }} />
        <canvas
          ref={canvasRef}
          onClick={onCanvasClick}
          aria-label={`Cross-modality heatmap: ${nRows} perturbed genes by ${nCols} measurement columns. Click a square for its value.`}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            zIndex: 1,
            cursor: "pointer",
            willChange: "transform",
          }}
        />
      </div>

      {/* Click-to-inspect value popover (positioned imperatively). */}
      <div
        ref={popoverRef}
        role="dialog"
        aria-label="Cell value"
        style={{
          position: "absolute",
          display: "none",
          zIndex: 20,
          maxWidth: 260,
          background: "#ffffff",
          border: "1px solid #d1d5db",
          borderRadius: 8,
          boxShadow: "0 6px 20px rgba(0,0,0,0.16)",
          padding: "8px 10px",
          fontSize: 12,
          color: "#1f2937",
          lineHeight: 1.35,
          pointerEvents: "auto",
        }}
      >
        {sel && (
          <>
            <div style={{ fontWeight: 600 }}>
              {sel.gene.humanSymbol ? (
                <a
                  className="matrix-link"
                  href={`/?perturbed=${encodeURIComponent(sel.gene.humanSymbol)}`}
                >
                  {selGeneName}
                </a>
              ) : (
                selGeneName
              )}{" "}
              <span style={{ color: "#9ca3af", fontWeight: 400 }}>(perturbed)</span>
            </div>
            <div style={{ marginTop: 1 }}>
              ×{" "}
              {sel.col.columnIsGene ? (
                <a
                  className="matrix-link"
                  href={`/?target=${encodeURIComponent(sel.col.label)}`}
                >
                  {sel.col.label}
                </a>
              ) : (
                sel.col.label
              )}{" "}
              <span style={{ color: "#9ca3af" }}>
                ({sel.col.columnIsGene ? "measured" : "phenotype"})
              </span>
            </div>
            <div style={{ color: "#6b7280", fontSize: 11, marginTop: 1 }}>
              {sel.col.sourceLabel}
            </div>
            <div style={{ marginTop: 5, fontWeight: 500 }}>{selValueText}</div>
          </>
        )}
      </div>

      {/* Screen-reader announcement of the selected cell. */}
      <div aria-live="polite" style={VISUALLY_HIDDEN}>
        {sel
          ? `${selGeneName} perturbed by ${sel.col.label}${
              sel.col.columnIsGene ? " measured" : " phenotype"
            }, ${sel.col.sourceLabel}: ${selValueText}`
          : ""}
      </div>
    </div>
  );
}
