import { useMemo } from "react";
import {
  type MatrixCell,
  type MatrixColumn,
  type MatrixGeneRow,
  type MatrixSection,
} from "@/lib/collated-matrix-types";
import { scaleColor, scaleFor } from "@/lib/matrix-color-scales";

/**
 * CollatedMatrix — the perturbed-gene × modality "red table" (epic #220),
 * rendered as a compact heatmap. Rows are experimentally-perturbed genes;
 * every column is a value sub-column of an expanded dataset (#213 removed the
 * old aggregated status columns). A column is either a measured target gene or a
 * phenotype (behavioral parameter, cell subcluster, brain region); its cells are
 * colored through the column's `metric` color scale.
 *
 * The header is two-tier: a band row ("experiment type · author-year", one cell
 * per source dataset, linking to Full-datasets) → per-column labels (target
 * genes link to a target search; phenotypes are plain text). It scrolls in a
 * single native bounded-height container (the page owns that) so horizontal
 * scrolling stays smooth; the header sticks to the top, the gene column freezes
 * left, and each perturbed-gene row header links to a perturbed search.
 */

const MATRIX_MAX_HEIGHT = "72vh";
const CELL = 17; // tile + ~1px gutter each side → ~2px between adjacent tiles
const ROW_H = CELL;
const COL_W = CELL;
const LABEL_W = 120; // frozen gene-label column width, px
const BAND_H = 22; // header band row ("experiment · author") height, px

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

// Rich hover text for one cell (native `title`) — names the perturbed gene, the
// column, the dataset, and the value in the column's metric.
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

// Contiguous run of columns sharing a dataset — the header band row.
interface BandGroup {
  gkey: string;
  bandLabel: string;
  sourceTable: string;
  tooltip: string | null;
  span: number;
}

export default function CollatedMatrix({
  sections,
  columns,
  genes,
  metricDomains,
}: {
  sections: MatrixSection[];
  columns: MatrixColumn[];
  genes: MatrixGeneRow[];
  metricDomains: MetricDomains;
}) {
  const sectionLabel = useMemo(
    () => new Map(sections.map((s) => [s.key, s.label])),
    [sections]
  );

  // One band cell per contiguous run of columns from the same dataset. The band
  // shows "experiment type · author-year" on one line and links to Full-datasets.
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
          {/* Row 1 — band: "experiment type · author-year", one cell per dataset,
              linking to that dataset's Full-datasets table. Sticky to the top
              (stays on vertical scroll) but not horizontally pinned. */}
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
                <a
                  className="matrix-link"
                  href={`/full-datasets?open=${encodeURIComponent(g.sourceTable)}`}
                >
                  {g.bandLabel}
                </a>
              </th>
            ))}
          </tr>
          {/* Row 2 — per-column labels (vertical). Gene columns link to a target
              search; phenotype columns are plain text. */}
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                title={
                  c.columnIsGene
                    ? `${c.label} — ${c.sourceLabel} (significant in ${c.nSigGroups} perturbations)`
                    : `${c.label} — ${c.sourceLabel}`
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
                  {c.columnIsGene ? (
                    <a
                      className="matrix-link"
                      href={`/?target=${encodeURIComponent(c.label)}`}
                    >
                      {c.label}
                    </a>
                  ) : (
                    c.label
                  )}
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
                  background: rowBg,
                  // Skip layout+paint for off-screen rows — only the visible ones
                  // paint per frame, which keeps scrolling a 40k-cell grid smooth.
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
                  // The tile is painted directly on the <td> (no child span): a
                  // 1px transparent border is the inter-tile gap (row stripe
                  // shows through), a padding-box layer draws the tile border, a
                  // content-box layer draws the fill.
                  return (
                    <td
                      key={c.key}
                      role="img"
                      aria-label={has ? fmtValue(c.metric, cell.value) : "No data"}
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
