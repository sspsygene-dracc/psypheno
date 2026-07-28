import { useMemo } from "react";
import DoubleScrollX from "@/components/DoubleScrollX";
import InfoTooltip from "@/components/InfoTooltip";
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
 * The header is three-tier: modality band → dataset band → per-column gene
 * labels. A DataTable can't express this (sticky multi-row header + frozen first
 * column), so it's purpose-built; horizontal scroll + sticky axes ride a
 * bounded-height DoubleScrollX.
 */

const MATRIX_MAX_HEIGHT = "72vh";
const TILE = 15; // color tile edge, px
const CELL = 17; // tile + ~1px gutter each side → ~2px between adjacent tiles
const ROW_H = CELL;
const COL_W = CELL;
const LABEL_W = 120; // frozen gene-label column width, px
const MODALITY_H = 22; // header row 1 (modality band) height, px
const DATASET_H = 20; // header row 2 (dataset band) height, px

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

// Short per-modality explanation for the modality-band (i) tooltip.
const MODALITY_INFO: Record<string, string> = {
  expression:
    "RNA differential expression. Each column is a measured target gene; the tile is -log10(p) of the perturbation's effect on it (red = most significant).",
  perturb_seq:
    "Perturb-seq differential expression across CRISPR perturbations. Each column is a measured target gene, colored by -log10(p).",
  perturb_fish:
    "Perturb-FISH spatial screen. Each column is a measured target gene, colored by -log10(qval) — an FDR, not a raw p-value.",
  behavior: "Behavioral phenotype screens (aggregated status across datasets).",
  morphology: "Morphology assays (aggregated status).",
  electrophysiology: "Electrophysiology assays (aggregated status).",
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

const NO_DATA_TILE = (
  <Tile fill={STATUS_META.none.fill} border={STATUS_META.none.border} label="No data" />
);

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
  label: string;
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
      groups.push({
        gkey,
        kind: c.kind,
        label: c.kind === "pvalue" ? c.sourceLabel : "",
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
  }, [columns]);

  const stickyLabel = (top: number) =>
    ({
      position: "sticky",
      top,
      zIndex: 5,
      background: "#f3f4f6",
      // Left-align so the inner sticky-left label starts at the section's left
      // edge; a th's default center alignment would push a wide section's label
      // to its (off-screen) middle and defeat the sticky-left ride-along.
      textAlign: "left",
      whiteSpace: "nowrap",
      borderBottom: "1px solid #e5e7eb",
      borderLeft: "1px solid #e5e7eb",
    }) as const;

  return (
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
            {/* Row 1 — modality band. Corner spans all three header rows. */}
            <tr>
              <th
                scope="col"
                rowSpan={3}
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
                <InfoTooltip
                  size={12}
                  text="Rows are experimentally perturbed SSPsyGene target genes — one row per perturbed gene. Hover any square for its value."
                />
              </th>
              {sections.map((s) => (
                <th
                  key={s.key}
                  scope="colgroup"
                  colSpan={s.span}
                  style={{ ...stickyLabel(0), height: MODALITY_H, padding: 0 }}
                >
                  {s.kind === "expanded" && (
                    <div
                      style={{
                        position: "sticky",
                        left: LABEL_W,
                        display: "inline-flex",
                        alignItems: "center",
                        padding: "0 8px",
                        fontSize: 12,
                        fontWeight: 700,
                        color: s.isEmpty ? "#9ca3af" : "#374151",
                      }}
                    >
                      {s.label}
                      {MODALITY_INFO[s.key] && (
                        <InfoTooltip size={11} text={MODALITY_INFO[s.key]} />
                      )}
                    </div>
                  )}
                </th>
              ))}
            </tr>
            {/* Row 2 — dataset band (one cell per dataset group). */}
            <tr>
              {datasetGroups.map((g) => (
                <th
                  key={g.gkey}
                  scope="colgroup"
                  colSpan={g.span}
                  style={{
                    ...stickyLabel(MODALITY_H),
                    height: DATASET_H,
                    padding: 0,
                  }}
                >
                  {g.kind === "pvalue" && (
                    <div
                      style={{
                        position: "sticky",
                        left: LABEL_W,
                        display: "inline-flex",
                        alignItems: "center",
                        padding: "0 8px",
                        fontSize: 11,
                        fontWeight: 600,
                        color: "#4b5563",
                      }}
                    >
                      {g.label}
                      {g.tooltip && <InfoTooltip size={11} text={g.tooltip} />}
                    </div>
                  )}
                </th>
              ))}
            </tr>
            {/* Row 3 — per-column vertical labels. */}
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
                    top: MODALITY_H + DATASET_H,
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
                          <Tile
                            fill={pColor(cell.negLogP)}
                            border="rgba(0,0,0,0.12)"
                            label={`-log10(p) ≈ ${cell.negLogP}`}
                          />
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
  );
}
