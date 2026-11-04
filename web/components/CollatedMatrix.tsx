import { useEffect, useMemo, useRef, useState } from "react";
import { EyeOff } from "lucide-react";
import {
  type CollatedCellResponse,
  type CollatedContribution,
  type PhenotypeTest,
  type MatrixCell,
  type MatrixColumn,
  type MatrixGeneRow,
  type MatrixSection,
} from "@/lib/collated-matrix-types";
import { scaleFor } from "@/lib/matrix-color-scales";
import {
  buildColorGrid,
  cellAgreement,
  cellAt,
  drawCells,
  COL_W,
  ROW_H,
  SUMMARY_COL_W,
  type LowerTriangleMode,
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
 * Because only the body is a real scroller, a wheel over the frozen gene column
 * or the header would otherwise chain straight to the page — the matrix sits
 * still while the document scrolls under it. A non-passive wheel listener on the
 * panel root forwards those deltas to the body instead, one axis per region:
 * the gene column scrolls rows, the column labels scroll columns (their vertical
 * wheel keeps its existing meaning — the label strip's own scroll).
 *
 * Header modes: with columns grouped by dataset (`bandsVisible`) a band row
 * ("experiment · author-year", with a hide control) sits above per-column labels.
 * When columns are clustered (`!bandsVisible`) the grouping is gone, so the
 * dataset folds into each column's single vertical label.
 */

const LABEL_W = 120; // frozen gene-label column width, px
// Header band row. The height has to follow the *narrowest* band: a band spans
// `span * colW`, so at 5 columns per dataset it is only ~85px wide and a heading
// like "RNA expression · Gordon 2026" needs three lines where a wide band needs
// one. Fixed at 34px it simply clipped. BAND_H_MIN keeps wide bands looking as
// they always did; BAND_H_MAX stops a pathological label from eating the panel
// (past it the heading clips again, but the hover tooltip still has it all).
const BAND_H_MIN = 34;
const BAND_H_MAX = 78;
const BAND_LINE_H = 13; // 11px text at line-height 1.15, rounded up
const BAND_CHAR_PX = 5.6; // ~advance of one 11px semibold char
const BAND_PAD_V = 9; // 3px top padding + breathing room under the last line
// Horizontal chrome inside a band: 4px padding each side, the 2px flex gap, and
// the ~15px hide button — none of it available to the heading text.
const BAND_CHROME_W = 25;
// The column-label strip shows this fixed height; when the longest label needs
// more (folded "modality · author · gene" labels in clustered mode run long),
// the strip scrolls vertically on its own instead of making the header taller.
const LABEL_STRIP_VISIBLE = 150;
const LABEL_STRIP_MIN = 120;
const LABEL_STRIP_MAX = 340;
const LABEL_CHAR_PX = 7; // ~advance of one 12px bold char along the rotated label
const LABEL_STRIP_PAD = 20; // padding above/below the rotated text
// Summary labels are dataset names over wide columns, so they read horizontally
// and wrap instead of rotating — a 50-char rotated label would need a 340px
// header strip, where four wrapped lines need ~62px.
const SUMMARY_LABEL_CHAR_PX = 6; // ~advance of one 11px char
const SUMMARY_LABEL_LINE_H = 13;
const SUMMARY_LABEL_PAD = 12;
const COL_OVERSCAN = 12; // extra columns rendered each side of the header window
const ROW_OVERSCAN = 24; // extra gene labels rendered each side of the row window
const DEFAULT_PANEL_H = "76vh"; // fixed panel height: both scrollbars live inside it

const ROW_STRIPE_EVEN = "#ffffff";
const ROW_STRIPE_ODD = "#fafbfc";
const WHEEL_LINE_PX = 16; // px per `deltaMode: DOM_DELTA_LINE` unit (Firefox)

/** Can `el` still move along `axis` in the direction of `delta`? */
function canScroll(el: HTMLElement, axis: "x" | "y", delta: number): boolean {
  const pos = axis === "x" ? el.scrollLeft : el.scrollTop;
  const max =
    axis === "x" ? el.scrollWidth - el.clientWidth : el.scrollHeight - el.clientHeight;
  return delta < 0 ? pos > 0.5 : pos < max - 0.5;
}

/**
 * Lines `text` wraps to in a box `perLine` characters wide, by the same greedy
 * word wrapping the browser does. Counting `length / perLine` instead
 * under-counts: "Behavioral · Fernandez Garcia 2026" is 34 characters, but at 10
 * characters per line its unbreakable words leave ragged ends and it takes five
 * lines, not four.
 */
function wrappedLineCount(text: string, perLine: number): number {
  if (perLine <= 0) return 1;
  let lines = 1;
  let used = 0;
  for (const word of text.split(/\s+/)) {
    if (!word) continue;
    if (used > 0 && used + 1 + word.length > perLine) {
      lines++;
      used = 0;
    }
    if (word.length > perLine) {
      // Longer than the box: breaks mid-word (or overflows, which costs the
      // same height). Rounding up here errs toward a taller band, not a clipped one.
      if (used > 0) {
        lines++;
        used = 0;
      }
      lines += Math.ceil(word.length / perLine) - 1;
      used = word.length % perLine || perLine;
    } else {
      used = used === 0 ? word.length : used + 1 + word.length;
    }
  }
  return lines;
}

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

/** How a summary column's `nSig` was counted — the wide phenotype axis only has
 *  a nominal p where the other axes have an FDR, so the popover says which. */
function sigRuleText(rule: string | undefined): string {
  return rule === "nominal_p<0.05" ? "nominal p < 0.05" : "FDR < 0.05";
}

/**
 * Popover text for a collapsed dataset column (#234). The cell's `value` is
 * log10(1 + n) — a color coordinate, not something to show a reader — so the
 * text is built from the raw counts the API ships alongside it.
 */
function summaryValueText(column: MatrixColumn, cell: MatrixCell): string {
  let head =
    `${(cell.nSig ?? 0).toLocaleString()} of ` +
    `${(cell.nMeasured ?? 0).toLocaleString()} readouts significant ` +
    `(${sigRuleText(column.sigRule)})`;
  if (cell.nInferred) {
    head +=
      ` · ${cell.nInferred.toLocaleString()} of those measured are inferred ` +
      `(the source lists only significant results; ` +
      (cell.inferredBasis === "library"
        ? "this gene is only on its perturbation list)"
        : "a readout counts as measured where it was a hit for another perturbation in the same cell type)");
  }
  // best_value 0 = no reported readout at all (every measurement inferred).
  if (cell.best === undefined || cell.best <= 0 || column.baseMetric === undefined)
    return head;
  return `${head} · strongest: ${fmtValue(column.baseMetric, cell.best)}`;
}

/**
 * Popover text for an inferred "tested, not significant" cell. The source
 * published only significant results, so there is no value to show — only
 * why the pair is believed to have been measured.
 */
function inferredValueText(cell: MatrixCell): string {
  return cell.inferred === "library"
    ? "Not reported — assumed tested, not significant. The source lists only " +
        "significant results; this gene is on its perturbation list but has no " +
        "reported result, so it is assumed tested in every cell type the table " +
        "covers (per-cell-type cell counts weren't published)."
    : "Not reported — inferred tested, not significant. The source lists only " +
        "significant results; this readout was a hit for another perturbation in " +
        "a cell type where this gene was also tested, so it was measured here too.";
}

/** Popover headline for a collated (by-readout) cell. */
function collatedValueText(cell: MatrixCell, lowerMode: LowerTriangleMode): string {
  const k = cell.k ?? 0;
  const n = cell.n ?? 0;
  let text = `${k} of ${n} ${n === 1 ? "study" : "studies"} significant (FDR < 0.05)`;
  if (k > 0) {
    const parts: string[] = [];
    if (cell.nUp) parts.push(`${cell.nUp} up`);
    if (cell.nDown) parts.push(`${cell.nDown} down`);
    const noDirection = k - (cell.nUp ?? 0) - (cell.nDown ?? 0);
    if (noDirection > 0) parts.push(`${noDirection} with no single direction`);
    if (parts.length) text += ` · ${parts.join(", ")}`;
  }
  if (cell.nInferred) {
    text += ` · ${cell.nInferred} measurement${cell.nInferred === 1 ? "" : "s"} inferred`;
  }
  if (lowerMode === "agreement") text += ` · ${agreementText(cell)}`;
  return text;
}

/** The agreement view's reading of a cell, for the popover. */
function agreementText(cell: MatrixCell): string {
  const a = cellAgreement(cell);
  const pos = cell.nPosAll ?? 0;
  const neg = cell.nNegAll ?? 0;
  const signs =
    cell.nPosAll === undefined
      ? ""
      : ` (effect signs over all studies: ${pos} up, ${neg} down` +
        (cell.nInferred ? "; inferred measurements have no effect size" : "") +
        ")";
  if (!a) return `fewer than two studies to compare${signs}`;
  if (a.strength === "strong") {
    return `significant studies ${a.agreement === "agree" ? "agree" : "disagree"} on direction${signs}`;
  }
  return `studies ${a.agreement === "agree" ? "agree" : "disagree"} on effect sign, counting non-significant ones${signs}`;
}

function fmtStat(v: number | null): string {
  if (v === null) return "—";
  return v < 0.001 ? v.toExponential(1) : v.toPrecision(2);
}

/**
 * The per-study breakdown behind a collated cell, fetched on demand from
 * /api/collated-cell (the matrix payload carries only k/n).
 */
function CollatedCellDetail({
  group,
  perturbedId,
  targetId,
}: {
  group: string;
  perturbedId: number;
  targetId: number;
}) {
  const [rows, setRows] = useState<CollatedContribution[] | null>(null);
  const [tests, setTests] = useState<PhenotypeTest[]>([]);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setTests([]);
    setFailed(false);
    fetch(
      `/api/collated-cell?group=${encodeURIComponent(group)}` +
        `&perturbed=${perturbedId}&target=${targetId}`
    )
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.json() as Promise<CollatedCellResponse>;
      })
      .then((json) => {
        if (cancelled) return;
        setRows(json.contributions);
        setTests(json.tests ?? []);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [group, perturbedId, targetId]);

  if (failed) return <div style={{ color: "#dc2626", marginTop: 6 }}>Couldn&rsquo;t load studies.</div>;
  if (rows === null) return <div style={{ color: "#9ca3af", marginTop: 6 }}>Loading studies&hellip;</div>;
  return (
    <>
    <ul style={{ listStyle: "none", padding: 0, margin: "6px 0 0 0" }}>
      {rows.map((r) => (
        <li key={r.study} style={{ marginTop: 4 }}>
          <span
            style={{
              fontWeight: 600,
              color: r.significant ? "#1f2937" : "#6b7280",
            }}
          >
            {r.significant ? "● " : "○ "}
            <a
              className="matrix-link"
              href={`/full-datasets?select=${encodeURIComponent(r.sourceTables.split(",")[0])}`}
            >
              {r.studyLabel}
            </a>
          </span>{" "}
          <span style={{ color: "#6b7280" }}>
            {r.inferredBasis
              ? r.inferredBasis === "library"
                ? "not reported; on the perturbation list, assumed tested; no effect size, so no vote on direction"
                : "not reported; inferred tested, not significant; no effect size, so no vote on direction"
              : `best FDR ${fmtStat(r.minFdr)}` +
                (r.effect
                  ? ` · effect ${r.effect > 0 ? "+" : ""}${r.effect.toFixed(2)} (${r.effect > 0 ? "up" : "down"})`
                  : // A significant pooled-phenotype study without an effect has
                    // significant measures both ways; elsewhere there is no
                    // effect column to take a sign from.
                    r.significant && group === "phenotype"
                    ? " · no single direction"
                    : " · no effect size, so no vote on direction") +
                ` · ${r.nTests} test${r.nTests === 1 ? "" : "s"}`}
          </span>
        </li>
      ))}
    </ul>
    {tests.length > 0 && <PhenotypeTests tests={tests} />}
    </>
  );
}

const MEASURE_LIST_STYLE = {
  listStyle: "none",
  padding: 0,
  margin: "2px 0 0 0",
  maxHeight: 170,
  overflowY: "auto",
} as const;

/** The original measures behind a pooled phenotype cell, strongest first. */
function PhenotypeTests({ tests }: { tests: PhenotypeTest[] }) {
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontWeight: 600, color: "#374151" }}>
        Measures in this cell ({tests.length})
      </div>
      <ul style={MEASURE_LIST_STYLE}>
        {tests.map((t, i) => (
          <li key={i} style={{ marginTop: 3 }}>
            <span style={{ color: t.fdr < 0.05 ? "#1f2937" : "#6b7280" }}>
              {t.fdr < 0.05 ? "● " : "○ "}
              {t.column}
            </span>{" "}
            <span style={{ color: "#6b7280" }}>
              {`${t.source} · FDR ${fmtStat(t.fdr)}`}
              {t.effect ? ` · ${t.effect > 0 ? "up" : "down"}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const CONTAINS_BUTTON_STYLE = {
  all: "unset",
  cursor: "pointer",
  color: "#2563eb",
  textDecoration: "underline dotted",
} as const;

const CONTAINS_PANEL_MAX_H = 280;

const CONTAINS_PANEL_STYLE = {
  position: "fixed",
  zIndex: 50,
  width: 340,
  maxWidth: "calc(100vw - 16px)",
  padding: "8px 10px",
  background: "#fff",
  border: "1px solid #d1d5db",
  borderRadius: 6,
  boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
  fontSize: 12,
  color: "#4b5563",
  maxHeight: CONTAINS_PANEL_MAX_H,
  overflowY: "auto",
  boxSizing: "border-box",
} as const;

/** What a pooled phenotype column combines. */
function PhenotypeContains({ contains }: { contains: NonNullable<MatrixColumn["contains"]> }) {
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontWeight: 600, color: "#374151" }}>
        This column combines ({contains.length})
      </div>
      <ul style={MEASURE_LIST_STYLE}>
        {contains.map((c) => (
          <li key={`${c.source}:${c.column}`} style={{ marginTop: 3 }}>
            {c.column} <span style={{ color: "#6b7280" }}>{c.source}</span>
          </li>
        ))}
      </ul>
    </div>
  );
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

/**
 * One column's vertical label. The gene / phenotype name is rendered first so
 * that — with the `vertical-rl` + rotate orientation — it sits at the bottom of
 * the strip, nearest the cells and visible by default; `datasetText` (folded /
 * clustered mode) reads above it and scrolls into view.
 */
const HLABEL_STYLE = {
  fontSize: 11,
  fontWeight: 600,
  color: "#374151",
  lineHeight: `${SUMMARY_LABEL_LINE_H}px`,
  textAlign: "center",
  overflowWrap: "anywhere",
  width: "100%",
  padding: "0 4px",
  boxSizing: "border-box",
} as const;

function ColumnLabel({
  column,
  datasetText,
  linkToDataset = false,
  horizontal = false,
  onShowContains,
}: {
  column: MatrixColumn;
  datasetText: string | null;
  /** Summary mode: the label *is* the dataset, so it carries the dataset link
   *  that the (suppressed) band row would otherwise provide. */
  linkToDataset?: boolean;
  /** Render across the column instead of rotated along it (wide columns). */
  horizontal?: boolean;
  /** Pooled phenotype columns: open the list of measures the column combines. */
  onShowContains?: (e: React.MouseEvent) => void;
}) {
  return (
    <div
      style={horizontal ? HLABEL_STYLE : VLABEL_STYLE}
      title={
        column.contains
          ? `Combines ${column.contains.length} measures: ` +
            [...new Set(column.contains.map((c) => c.column))].join(", ")
          : undefined
      }
    >
      {column.contains && onShowContains ? (
        <button
          type="button"
          data-contains-trigger=""
          onClick={onShowContains}
          style={CONTAINS_BUTTON_STYLE}
        >
          {column.label} ({column.contains.length})
        </button>
      ) : column.columnIsGene ? (
        <a
          className="matrix-link"
          href={`/?target=${encodeURIComponent(column.label)}`}
        >
          {column.label}
        </a>
      ) : linkToDataset ? (
        <a
          className="matrix-link"
          href={`/full-datasets?open=${encodeURIComponent(column.sourceTable)}`}
        >
          {column.label}
        </a>
      ) : (
        column.label
      )}
      {datasetText && (
        <>
          {" · "}
          <a
            className="matrix-link"
            href={`/full-datasets?open=${encodeURIComponent(column.sourceTable)}`}
          >
            {datasetText}
          </a>
        </>
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
  summary = false,
  lowerMode = "direction",
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
   * Summary view (#234): each column *is* a dataset. Widens the column pitch (a
   * handful of 17px columns is a ribbon adrift in the page), drops the dataset
   * prefix from the labels (it would repeat the label itself), and words the
   * popover in readout counts. Pass `bandsVisible={false}` with it — a band over
   * a single column has no room for its own heading.
   */
  summary?: boolean;
  /** By-readout view: what the lower-right triangle of each cell shows. */
  lowerMode?: LowerTriangleMode;
  /**
   * Fixed panel height. Both the vertical and horizontal scrollbars live inside
   * this panel and the header stays pinned; the surrounding page doesn't scroll
   * the matrix.
   */
  panelHeight?: number | string;
}) {
  const nRows = genes.length;
  const nCols = columns.length;
  const colW = summary ? SUMMARY_COL_W : COL_W;

  const sectionLabel = useMemo(
    () => new Map(sections.map((s) => [s.key, s.label])),
    [sections]
  );

  // Height needed to show the longest visible column label without clipping.
  // In folded (clustered) mode the label carries the dataset prefix, so it's
  // much longer than a plain gene/phenotype name in banded mode.
  const labelStripH = useMemo(() => {
    if (summary) {
      // 8px: the label's 4px side padding. Word-aware, like the band headings —
      // a plain length / perLine undercounts wrapped lines and clipped the top
      // of long labels ("Protein interactions · Wang 2026 · …").
      const perLine = Math.max(
        1,
        Math.floor((colW - 8) / SUMMARY_LABEL_CHAR_PX)
      );
      let maxLines = 1;
      for (const c of columns) {
        maxLines = Math.max(maxLines, wrappedLineCount(c.label, perLine));
      }
      return maxLines * SUMMARY_LABEL_LINE_H + SUMMARY_LABEL_PAD;
    }
    let maxLen = 0;
    for (const c of columns) {
      const len = bandsVisible
        ? c.label.length
        : (sectionLabel.get(c.section) ?? c.section).length +
          3 +
          c.sourceLabel.length +
          3 +
          c.label.length;
      if (len > maxLen) maxLen = len;
    }
    return Math.min(
      LABEL_STRIP_MAX,
      Math.max(LABEL_STRIP_MIN, Math.round(maxLen * LABEL_CHAR_PX + LABEL_STRIP_PAD))
    );
  }, [columns, bandsVisible, summary, colW, sectionLabel]);
  // The strip's on-screen height stays fixed; its scrollable content is as tall
  // as the longest label needs (min the visible height so short labels fill it).
  // Summary labels are dataset names, and there are only a handful of columns —
  // give the strip the height it needs rather than making it scroll.
  const stripVisibleH = summary ? labelStripH : LABEL_STRIP_VISIBLE;
  const stripContentH = Math.max(labelStripH, stripVisibleH);

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

  // Tall enough for the band that wraps to the most lines (see BAND_H_MIN).
  const bandH = useMemo(() => {
    let maxLines = 1;
    for (const g of bandLayout) {
      const textW = g.span * colW - BAND_CHROME_W;
      const perLine = Math.max(1, Math.floor(textW / BAND_CHAR_PX));
      maxLines = Math.max(maxLines, wrappedLineCount(g.bandLabel, perLine));
    }
    return Math.min(
      BAND_H_MAX,
      Math.max(BAND_H_MIN, maxLines * BAND_LINE_H + BAND_PAD_V)
    );
  }, [bandLayout, colW]);

  const HEADER_H = (bandsVisible ? bandH : 0) + stripVisibleH;

  // Every cell's color, precomputed once per data/order change (packed RGB +
  // present-mask). Scrolling never recomputes a color.
  const colorGrid = useMemo(
    () => buildColorGrid(genes, columns, metricDomains, lowerMode),
    [genes, columns, metricDomains, lowerMode]
  );

  const rootRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);
  const rowLabelsColRef = useRef<HTMLDivElement>(null);
  const bandInnerRef = useRef<HTMLDivElement>(null);
  const labelStripRef = useRef<HTMLDivElement>(null);
  const labelInnerRef = useRef<HTMLDivElement>(null);
  const rowLabelsInnerRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const dprRef = useRef(1);

  // Viewport client size of the body scroller (drives canvas backing store).
  const [size, setSize] = useState({ w: 0, h: 0 });
  // Visible spans of columns / rows for windowing the DOM header + gene column.
  const [colWindow, setColWindow] = useState({ start: 0, end: 0 });
  const [rowWindow, setRowWindow] = useState({ start: 0, end: 0 });
  const [selected, setSelected] = useState<{ row: number; col: number } | null>(null);
  // The phenotype column whose label was clicked, and where.
  const [containsOpen, setContainsOpen] = useState<{
    column: MatrixColumn;
    x: number;
    top?: number;
    bottom?: number;
  } | null>(null);
  const containsRef = useRef<HTMLDivElement>(null);

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
      colW,
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
    const cellX = selected.col * colW - sl;
    const cellY = selected.row * ROW_H - st;
    if (cellX < -colW || cellX > vw || cellY < -ROW_H || cellY > vh) {
      pop.style.display = "none";
      return;
    }
    pop.style.display = "block";
    const rootW = rootRef.current?.clientWidth ?? vw + LABEL_W;
    const popW = pop.offsetWidth || 220;
    let left = LABEL_W + cellX + colW + 6;
    if (left + popW > rootW - 4) left = LABEL_W + cellX - popW - 6;
    if (left < 4) left = 4;
    pop.style.left = `${left}px`;
    pop.style.top = `${HEADER_H + cellY + ROW_H}px`;
  };

  // Body scroll: imperatively slave the header/gene-column/canvas to the offset
  // (rAF-coalesced), redraw, reposition the popover, and update the DOM windows
  // only when the visible span actually shifts.
  const prevColWRef = useRef<number | null>(null);
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
      if (bandInnerRef.current)
        bandInnerRef.current.style.transform = `translateX(${-sl}px)`;
      if (labelInnerRef.current)
        labelInnerRef.current.style.transform = `translateX(${-sl}px)`;
      if (rowLabelsInnerRef.current)
        rowLabelsInnerRef.current.style.transform = `translateY(${-st}px)`;
      if (canvasRef.current)
        canvasRef.current.style.transform = `translate(${sl}px, ${st}px)`;
      drawRef.current();
      positionRef.current(sl, st, vw, vh);
      const cStart = Math.max(0, Math.floor(sl / colW) - COL_OVERSCAN);
      const cEnd = Math.min(nCols, Math.ceil((sl + vw) / colW) + COL_OVERSCAN);
      const rStart = Math.max(0, Math.floor(st / ROW_H) - ROW_OVERSCAN);
      const rEnd = Math.min(nRows, Math.ceil((st + vh) / ROW_H) + ROW_OVERSCAN);
      setColWindow((p) => (p.start === cStart && p.end === cEnd ? p : { start: cStart, end: cEnd }));
      setRowWindow((p) => (p.start === rStart && p.end === rEnd ? p : { start: rStart, end: rEnd }));
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(frame);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    // The column set changed (mode, columns per dataset, hidden datasets…):
    // bring the offsets back inside the new content before syncing. The browser
    // won't clamp them for us — the canvas is translated by the *old* offset and
    // its own box keeps the scrollable overflow that wide, so a narrower grid
    // would come up scrolled past its last column (blank headers and cells). A
    // mode switch changes the column pitch, so the old offset means nothing
    // there; start the new view from the left edge.
    const modeChanged = prevColWRef.current !== null && prevColWRef.current !== colW;
    prevColWRef.current = colW;
    const maxLeft = Math.max(0, nCols * colW - el.clientWidth);
    const maxTop = Math.max(0, nRows * ROW_H - el.clientHeight);
    const left = modeChanged ? 0 : Math.min(el.scrollLeft, maxLeft);
    const top = Math.min(el.scrollTop, maxTop);
    if (left !== el.scrollLeft || top !== el.scrollTop) {
      if (canvasRef.current)
        canvasRef.current.style.transform = `translate(${left}px, ${top}px)`;
      el.scrollLeft = left;
      el.scrollTop = top;
    }
    frame(); // initial sync
    return () => {
      if (raf) cancelAnimationFrame(raf);
      el.removeEventListener("scroll", onScroll);
    };
  }, [nRows, nCols, colW]);

  // Wheel over the panel's non-scrolling regions: forward it to the body (the
  // only real scroller) instead of letting it chain to the page. One axis per
  // region — the gene column scrolls rows, the column labels scroll columns —
  // so pointing at a label and scrolling moves the matrix along that label's own
  // direction. Over the header a vertical wheel still drives the label strip's
  // own scroll, which is what reveals the long folded labels.
  //
  // Registered by hand rather than via `onWheel`: React attaches wheel listeners
  // passively, where `preventDefault()` is a no-op. Deltas are only consumed when
  // the target scroller can actually move, so hitting an edge chains to the page
  // exactly as it already does over the body.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const onWheel = (e: WheelEvent) => {
      const body = scrollRef.current;
      if (!body) return;
      const t = e.target as Node;
      if (body.contains(t)) return; // the body scrolls natively; don't double it

      let dx = e.deltaX;
      let dy = e.deltaY;
      if (e.deltaMode === 1) {
        dx *= WHEEL_LINE_PX;
        dy *= WHEEL_LINE_PX;
      } else if (e.deltaMode === 2) {
        dx *= body.clientWidth;
        dy *= body.clientHeight;
      }
      // Shift+wheel is the mouse-only way to scroll sideways; most browsers
      // pre-swap the axes, but fold it in ourselves for the ones that don't.
      if (e.shiftKey && dx === 0) {
        dx = dy;
        dy = 0;
      }

      let consumed = false;
      const strip = labelStripRef.current;
      if (headerRef.current?.contains(t)) {
        if (dx && canScroll(body, "x", dx)) {
          body.scrollLeft += dx;
          consumed = true;
        }
        if (dy && strip && canScroll(strip, "y", dy)) {
          strip.scrollTop += dy;
          consumed = true;
        }
      } else if (rowLabelsColRef.current?.contains(t)) {
        if (dy && canScroll(body, "y", dy)) {
          body.scrollTop += dy;
          consumed = true;
        }
      } else {
        // Corner and any other panel chrome: behave like the body, both axes.
        if (dx && canScroll(body, "x", dx)) {
          body.scrollLeft += dx;
          consumed = true;
        }
        if (dy && canScroll(body, "y", dy)) {
          body.scrollTop += dy;
          consumed = true;
        }
      }
      if (consumed) e.preventDefault();
    };
    root.addEventListener("wheel", onWheel, { passive: false });
    return () => root.removeEventListener("wheel", onWheel);
  }, []);

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

  // Default the label strip scrolled to its bottom, so each label's tail (the
  // gene/phenotype name) sits next to the cells and the longer dataset prefix is
  // what scrolls into view above.
  useEffect(() => {
    const strip = labelStripRef.current;
    if (strip) strip.scrollTop = strip.scrollHeight;
  }, [stripContentH, bandsVisible, nCols]);

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

  // Dismiss the column-contents panel on Escape or an outside mousedown.
  useEffect(() => {
    if (!containsOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setContainsOpen(null);
    };
    const onDown = (e: MouseEvent) => {
      const target = e.target as Element;
      if (containsRef.current?.contains(target)) return;
      // The label buttons toggle the panel themselves on click.
      if (target.closest?.("[data-contains-trigger]")) return;
      setContainsOpen(null);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [containsOpen]);

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
      nCols,
      colW
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
      ? summary
        ? summaryValueText(sel.col, selCell)
        : selCell.k !== undefined
          ? collatedValueText(selCell, lowerMode)
        : selCell.inferred !== undefined
          ? inferredValueText(selCell)
          : fmtValue(sel.col.metric, selCell.value) +
            (selCell.sharedWith
              ? ` · same data as ${selCell.sharedWith}, not independent evidence`
              : "")
      : "No data"
    : "";

  return (
    <div
      ref={rootRef}
      style={{
        position: "relative",
        height: panelHeight,
        display: "grid",
        gridTemplateColumns: `${LABEL_W}px 1fr`,
        gridTemplateRows: `${HEADER_H}px 1fr`,
        // A handful of wide summary columns doesn't fill a 94vw page — cap the
        // panel at its content so it doesn't trail off into empty row stripes.
        // (+16 leaves room for the body's vertical scrollbar.)
        maxWidth: summary ? LABEL_W + nCols * colW + 16 : undefined,
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

      {/* Header (pinned top; slaved horizontally to the body scroll). A fixed
          band row (grouped mode) sits above the column-label strip, which keeps
          a fixed on-screen height and scrolls vertically on its own when the
          labels are taller than it (folded labels in clustered mode). */}
      <div
        ref={headerRef}
        style={{
          gridColumn: 2,
          gridRow: 1,
          overflow: "hidden",
          background: "#f9fafb",
          borderBottom: "1px solid #e5e7eb",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Dataset bands (grouped mode only) — fixed, doesn't scroll. */}
        {bandsVisible && (
          <div
            style={{
              height: bandH,
              flexShrink: 0,
              overflow: "hidden",
              position: "relative",
            }}
          >
            <div
              ref={bandInnerRef}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: nCols * colW,
                height: bandH,
                willChange: "transform",
              }}
            >
              {bandLayout
                .filter(
                  (g) => g.startCol < colWindow.end && g.startCol + g.span > colWindow.start
                )
                .map((g) => (
                  <div
                    key={g.gkey}
                    title={g.tooltip ?? undefined}
                    style={{
                      position: "absolute",
                      left: g.startCol * colW,
                      top: 0,
                      width: g.span * colW,
                      height: bandH,
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
            </div>
          </div>
        )}

        {/* Column-label strip — fixed on-screen height, scrolls vertically on
            its own so long (folded) labels are reachable without a tall header. */}
        <div
          ref={labelStripRef}
          className="matrix-label-strip"
          style={{
            flex: 1,
            overflowX: "hidden",
            overflowY: "auto",
            position: "relative",
          }}
        >
          <div
            ref={labelInnerRef}
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: nCols * colW,
              height: stripContentH,
              willChange: "transform",
            }}
          >
            {columns.slice(colWindow.start, colWindow.end).map((c, idx) => {
              const j = colWindow.start + idx;
              const modality = sectionLabel.get(c.section) ?? c.section;
              // In summary mode the label already *is* the dataset, so folding
              // the dataset in again would read "Zheng 2024 · Perturb-seq · Zheng 2024".
              const datasetText =
                bandsVisible || summary ? null : `${modality} · ${c.sourceLabel}`;
              return (
                <div
                  key={c.key}
                  title={
                    summary
                      ? `${modality} — ${c.sourceMediumLabel ?? c.label} ` +
                        `(${c.nSigGroups.toLocaleString()} readouts)`
                      : (bandsVisible ? "" : `${modality} · ${c.sourceLabel} — `) +
                        (c.columnIsGene
                          ? `${c.label} (significant in ${c.nSigGroups} perturbations)`
                          : c.label)
                  }
                  style={{
                    position: "absolute",
                    left: j * colW,
                    top: 0,
                    width: colW,
                    height: stripContentH,
                    overflow: "hidden",
                    display: "flex",
                    justifyContent: "center",
                    alignItems: "flex-end",
                    paddingBottom: 4,
                    boxSizing: "border-box",
                  }}
                >
                  <ColumnLabel
                    column={c}
                    datasetText={datasetText}
                    linkToDataset={summary}
                    horizontal={summary}
                    onShowContains={(e) => {
                      // Open below the label strip so the list never covers
                      // the neighbouring labels; a second click closes it.
                      const strip = labelStripRef.current?.getBoundingClientRect();
                      const x = e.currentTarget.getBoundingClientRect().left;
                      // Below the strip if the panel fits there, else ending
                      // just above it.
                      const below = strip ? strip.bottom + 4 : e.clientY + 10;
                      const place =
                        below + CONTAINS_PANEL_MAX_H <= window.innerHeight
                          ? { top: below }
                          : { bottom: window.innerHeight - (strip ? strip.top - 4 : e.clientY - 10) };
                      setContainsOpen((prev) =>
                        prev?.column.key === c.key ? null : { column: c, x, ...place }
                      );
                    }}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Frozen gene column (pinned left; slaved vertically to the body scroll). */}
      <div
        ref={rowLabelsColRef}
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
        <div style={{ width: nCols * colW, height: nRows * ROW_H }} />
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
          maxWidth: 340,
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
                ({summary ? "dataset" : sel.col.columnIsGene ? "measured" : "phenotype"})
              </span>
            </div>
            <div style={{ color: "#6b7280", fontSize: 11, marginTop: 1 }}>
              {/* In summary mode the line above already carries the author-year,
                  so show the fuller dataset identity instead of repeating it. */}
              {(summary ? sel.col.sourceMediumLabel : null) ?? sel.col.sourceLabel}
            </div>
            <div style={{ marginTop: 5, fontWeight: 500 }}>{selValueText}</div>
            {sel.col.columnIsGene && sel.gene.humanSymbol && !summary && (
              <div style={{ marginTop: 4 }}>
                <a
                  className="matrix-link"
                  href={
                    `/?perturbed=${encodeURIComponent(sel.gene.humanSymbol)}` +
                    `&target=${encodeURIComponent(sel.col.label)}`
                  }
                >
                  {sel.gene.humanSymbol} &rarr; {sel.col.label} in every dataset
                </a>
              </div>
            )}
            {selCell?.k !== undefined && sel.col.key.startsWith("col:") && (
              <CollatedCellDetail
                group={sel.col.section}
                perturbedId={sel.gene.centralGeneId}
                targetId={Number(sel.col.key.split(":")[2])}
              />
            )}
            {selCell === undefined && sel.col.contains && (
              <PhenotypeContains contains={sel.col.contains} />
            )}
          </>
        )}
      </div>

      {/* Screen-reader announcement of the selected cell. */}
      <div aria-live="polite" style={VISUALLY_HIDDEN}>
        {sel
          ? `${selGeneName} perturbed by ${sel.col.label}${
              summary
                ? " dataset"
                : sel.col.columnIsGene
                  ? " measured"
                  : " phenotype"
            }, ${sel.col.sourceLabel}: ${selValueText}`
          : ""}
      </div>

      {containsOpen?.column.contains && (
        <div
          ref={containsRef}
          role="dialog"
          aria-label={`What ${containsOpen.column.label} combines`}
          style={{
            ...CONTAINS_PANEL_STYLE,
            left: Math.max(8, Math.min(containsOpen.x, window.innerWidth - 356)),
            ...(containsOpen.top !== undefined
              ? { top: containsOpen.top }
              : { bottom: Math.max(8, containsOpen.bottom ?? 8) }),
          }}
        >
          <div style={{ fontWeight: 600, color: "#111827" }}>
            {containsOpen.column.label}
          </div>
          <PhenotypeContains contains={containsOpen.column.contains} />
        </div>
      )}
    </div>
  );
}
