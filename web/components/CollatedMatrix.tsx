import { useEffect, useMemo, useRef, useState } from "react";
import { EyeOff } from "lucide-react";
import {
  type MatrixCell,
  type MatrixColumn,
  type MatrixGeneRow,
  type MatrixSection,
} from "@/lib/collated-matrix-types";
import { scaleColor, scaleFor } from "@/lib/matrix-color-scales";

/**
 * CollatedMatrix — the perturbed-gene × modality "red table" (epic #220),
 * rendered as a compact heatmap. Rows are experimentally-perturbed genes; every
 * column is a value sub-column of an expanded dataset, colored through the
 * column's `metric` color scale.
 *
 * Layout (#213): the browser owns vertical scrolling — the table grows to full
 * height and the page scrolls, so the header scrolls away with it (the perturbed
 * gene column stays frozen at the left). Horizontal scrolling happens in the
 * content box; a slim proxy scrollbar pinned to the bottom of the viewport keeps
 * it reachable while scrolled down.
 *
 * Header modes: with columns grouped by dataset (`bandsVisible`), a band row
 * ("experiment · author-year", with a hide control) sits above per-column
 * labels. When columns are clustered (`!bandsVisible`) the grouping is gone, so
 * the dataset folds into each column's single vertical label.
 */

const CELL = 17; // tile + ~1px gutter each side → ~2px between adjacent tiles
const ROW_H = CELL;
const COL_W = CELL;
const LABEL_W = 120; // frozen gene-label column width, px
const BAND_H = 34; // header band row — tall enough for a wrapped dataset heading

const NO_DATA_FILL = "#fcfcfd";
const NO_DATA_BORDER = "#eef0f2";

export type MetricDomains = Record<string, [number, number] | null>;

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

function cellTitle(
  gene: string,
  column: MatrixColumn,
  cell: MatrixCell | undefined
): string {
  const noun = column.columnIsGene ? "measured" : "phenotype";
  if (cell === undefined) {
    return `${gene} (perturbed) × ${column.label} (${noun}) — ${column.sourceLabel}: no data`;
  }
  return (
    `${gene} (perturbed) × ${column.label} (${noun}) — ${column.sourceLabel}\n` +
    fmtValue(column.metric, cell.value)
  );
}

interface BandGroup {
  gkey: string;
  bandLabel: string;
  sourceTable: string;
  tooltip: string | null;
  span: number;
}

const VLABEL_STYLE = {
  writingMode: "vertical-rl",
  transform: "rotate(180deg)",
  margin: "0 auto",
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

export default function CollatedMatrix({
  sections,
  columns,
  genes,
  metricDomains,
  bandsVisible,
  onToggleHide,
}: {
  sections: MatrixSection[];
  columns: MatrixColumn[];
  genes: MatrixGeneRow[];
  metricDomains: MetricDomains;
  /** When true, columns are grouped by dataset and a band row is shown. */
  bandsVisible: boolean;
  onToggleHide: (sourceTable: string) => void;
}) {
  const sectionLabel = useMemo(
    () => new Map(sections.map((s) => [s.key, s.label])),
    [sections]
  );

  const datasetGroups = useMemo<BandGroup[]>(() => {
    const groups: BandGroup[] = [];
    for (const c of columns) {
      const gkey = `${c.section}|${c.sourceTable}`;
      const last = groups[groups.length - 1];
      if (last && last.gkey === gkey) {
        last.span++;
        continue;
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
      });
    }
    return groups;
  }, [columns, sectionLabel]);

  // Reachable horizontal scrollbar: a slim proxy pinned to the viewport bottom,
  // scroll-synced with the content box (whose own bar is hidden). Tolerance guard
  // avoids the subpixel ping-pong that used to flicker.
  const contentRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const syncing = useRef<null | "content" | "bar">(null);
  const [scrollWidth, setScrollWidth] = useState(0);

  useEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    const update = () => setScrollWidth(content.scrollWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(content);
    const table = content.firstElementChild;
    if (table) ro.observe(table);
    return () => ro.disconnect();
  }, [columns.length]);

  const onContentScroll = () => {
    if (syncing.current === "bar") return;
    const c = contentRef.current;
    const b = barRef.current;
    if (!c || !b || Math.abs(c.scrollLeft - b.scrollLeft) < 1) return;
    syncing.current = "content";
    b.scrollLeft = c.scrollLeft;
    requestAnimationFrame(() => {
      syncing.current = null;
    });
  };
  const onBarScroll = () => {
    if (syncing.current === "content") return;
    const c = contentRef.current;
    const b = barRef.current;
    if (!c || !b || Math.abs(c.scrollLeft - b.scrollLeft) < 1) return;
    syncing.current = "bar";
    c.scrollLeft = b.scrollLeft;
    requestAnimationFrame(() => {
      syncing.current = null;
    });
  };

  return (
    <div style={{ position: "relative" }}>
      <div
        ref={contentRef}
        className="matrix-scroll"
        onScroll={onContentScroll}
        style={{
          overflowX: "auto",
          border: "1px solid #e5e7eb",
          borderRadius: 12,
        }}
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
          <colgroup>
            <col style={{ width: LABEL_W }} />
            {columns.map((c) => (
              <col key={c.key} style={{ width: COL_W }} />
            ))}
          </colgroup>
          <thead>
            {/* Corner + (when grouped) the dataset band row. */}
            <tr>
              <th
                scope="col"
                rowSpan={2}
                title="Rows are experimentally perturbed SSPsyGene target genes — one row per perturbed gene. Hover any square for its value."
                style={{
                  position: "sticky",
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
                  borderBottom: "1px solid #e5e7eb",
                  borderRight: "1px solid #e5e7eb",
                  lineHeight: 1.2,
                }}
              >
                Perturbed gene ↓
              </th>
              {bandsVisible &&
                datasetGroups.map((g) => (
                  <th
                    key={g.gkey}
                    scope="colgroup"
                    colSpan={g.span}
                    title={g.tooltip ?? undefined}
                    style={{
                      background: "#f3f4f6",
                      height: BAND_H,
                      verticalAlign: "top",
                      textAlign: "left",
                      fontSize: 11,
                      fontWeight: 600,
                      color: "#374151",
                      overflow: "hidden",
                      padding: "3px 4px",
                      borderBottom: "1px solid #e5e7eb",
                      borderLeft: "1px solid #e5e7eb",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 2 }}>
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
                  </th>
                ))}
            </tr>
            {/* Per-column vertical labels (dataset folded in when clustered). */}
            <tr>
              {columns.map((c) => {
                const modality = sectionLabel.get(c.section) ?? c.section;
                const datasetText = bandsVisible
                  ? null
                  : `${modality} · ${c.sourceLabel}`;
                return (
                  <th
                    key={c.key}
                    scope="col"
                    title={
                      (bandsVisible ? "" : `${modality} · ${c.sourceLabel} — `) +
                      (c.columnIsGene
                        ? `${c.label} (significant in ${c.nSigGroups} perturbations)`
                        : c.label)
                    }
                    style={{
                      position: "sticky",
                      top: 0,
                      zIndex: 5,
                      background: "#f9fafb",
                      verticalAlign: "bottom",
                      padding: "6px 0",
                      borderBottom: "1px solid #e5e7eb",
                    }}
                  >
                    <ColumnLabel column={c} datasetText={datasetText} />
                  </th>
                );
              })}
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
                    background: rowBg,
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
                      maxWidth: LABEL_W,
                      borderRight: "1px solid #e5e7eb",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
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
                  </th>
                  {columns.map((c) => {
                    const cell = g.cells[c.key];
                    const has = cell !== undefined;
                    const fill = has
                      ? scaleColor(c.metric, cell.value, metricDomains[c.metric])
                      : NO_DATA_FILL;
                    const border = has ? "rgba(0,0,0,0.12)" : NO_DATA_BORDER;
                    return (
                      <td
                        key={c.key}
                        role="img"
                        aria-label={has ? fmtValue(c.metric, cell.value) : "No data"}
                        title={cellTitle(gene, c, cell)}
                        style={{
                          boxSizing: "border-box",
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
      {/* Slim horizontal scrollbar pinned to the viewport bottom. */}
      <div
        ref={barRef}
        className="matrix-hscroll"
        onScroll={onBarScroll}
        aria-hidden="true"
        style={{ position: "sticky", bottom: 0 }}
      >
        <div style={{ width: scrollWidth, height: 1 }} />
      </div>
    </div>
  );
}
