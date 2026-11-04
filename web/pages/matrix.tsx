import { useEffect, useMemo, useState } from "react";
import Head from "next/head";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import CollatedMatrix, { type MetricDomains } from "@/components/CollatedMatrix";
import {
  AGREEMENT_COLORS,
  AGREEMENT_NOTHING_TO_COMPARE,
  INFERRED_DOT,
  INFERRED_FILL,
  SHARED_MARK,
  type LowerTriangleMode,
} from "@/lib/matrix-canvas";
import {
  legendEndpoints,
  legendGradientCss,
  scaleColorRGB,
  scaleFor,
} from "@/lib/matrix-color-scales";
import { orderColumns, orderRows } from "@/lib/matrix-clustering";
import type {
  CollatedMatrixResponse,
  MatrixMode,
} from "@/lib/collated-matrix-types";

const COLS_PER_DATASET_OPTIONS = [5, 25, 50, 100, 200];
const READOUT_OPTIONS = [50, 100, 200, 500];

function ToggleButton({
  active,
  onClick,
  disabled,
  children,
}: {
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      disabled={disabled}
      style={{
        padding: "4px 10px",
        background: active ? "#e5e7eb" : "#ffffff",
        border: "1px solid #d1d5db",
        color: disabled ? "#9ca3af" : "#1f2937",
        borderRadius: 6,
        cursor: disabled ? "default" : "pointer",
        fontSize: 13,
        fontWeight: active ? 700 : 500,
      }}
    >
      {children}
    </button>
  );
}

/** True when any cell is an inferred "tested, not significant" pair. */
function hasInferredCells(data: CollatedMatrixResponse): boolean {
  return data.genes.some((g) => {
    for (const key in g.cells) if (g.cells[key].inferred !== undefined) return true;
    return false;
  });
}

/** True when any cell repeats a value from another study. */
function hasSharedCells(data: CollatedMatrixResponse): boolean {
  return data.genes.some((g) => {
    for (const key in g.cells) if (g.cells[key].sharedWith !== undefined) return true;
    return false;
  });
}

// By-readout cells carry two metrics, one per triangle: this says which is which.
const LEGEND_TRIANGLES: Record<string, string> = {
  frac_sig: "0,0 14,0 0,14",
  direction_agreement: "14,0 14,14 0,14",
};

function TriangleKey({ points }: { points: string }) {
  return (
    <svg
      aria-hidden="true"
      width="14"
      height="14"
      viewBox="0 0 14 14"
      style={{ flexShrink: 0 }}
    >
      <rect width="14" height="14" fill="#e5e7eb" />
      <polygon points={points} fill="#374151" />
    </svg>
  );
}

const rgbCss = ([r, g, b]: [number, number, number]) => `rgb(${r}, ${g}, ${b})`;

/** Legend for the agreement view's lower triangle: four swatches. */
function AgreementLegend() {
  const swatch = (rgb: [number, number, number], text: string) => (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span
        aria-hidden="true"
        style={{
          display: "inline-block",
          width: 12,
          height: 12,
          borderRadius: 2,
          border: "1px solid rgba(0,0,0,0.12)",
          background: rgbCss(rgb),
        }}
      />
      {text}
    </span>
  );
  return (
    <div
      style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, color: "#4b5563" }}
    >
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          fontWeight: 600,
          color: "#374151",
        }}
      >
        <TriangleKey points={LEGEND_TRIANGLES.direction_agreement} />
        do the studies agree on direction?
      </span>
      <span style={{ display: "inline-flex", gap: 12, flexWrap: "wrap" }}>
        {swatch(AGREEMENT_COLORS.agree, "agree")}
        {swatch(AGREEMENT_COLORS.disagree, "disagree")}
        <span style={{ color: "#9ca3af" }}>among 2+ significant studies</span>
      </span>
      <span style={{ display: "inline-flex", gap: 12, flexWrap: "wrap" }}>
        {swatch(AGREEMENT_NOTHING_TO_COMPARE, "nothing to compare")}
        <span style={{ color: "#9ca3af" }}>only one study found it significant</span>
      </span>
      <span style={{ color: "#9ca3af", fontSize: 11 }}>
        a whole tile in one color = no study found it significant
      </span>
    </div>
  );
}

/**
 * By-readout view: an enlarged example tile with both halves labelled, so a
 * first-time reader can decode a cell from the legend alone.
 */
function CellKey({ lowerMode }: { lowerMode: LowerTriangleMode }) {
  const lowerText =
    lowerMode === "agreement"
      ? "lower right: do the studies agree on direction?"
      : "lower right: which way the significant studies went";
  return (
    <div
      style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#4b5563" }}
    >
      <svg aria-hidden="true" width="34" height="34" viewBox="0 0 34 34" style={{ flexShrink: 0 }}>
        <polygon points="0,0 34,0 0,34" fill={rgbCss(scaleColorRGB("frac_sig", 0.75, null))} />
        <polygon
          points="34,0 34,34 0,34"
          fill={rgbCss(
            lowerMode === "agreement"
              ? AGREEMENT_COLORS.agree
              : scaleColorRGB("direction_agreement", 1, null)
          )}
        />
      </svg>
      <span style={{ display: "flex", flexDirection: "column", gap: 1 }}>
        <span style={{ fontWeight: 600, color: "#374151" }}>Reading a cell</span>
        <span>upper left: how many of the studies found a significant change</span>
        <span>{lowerText}</span>
        <span style={{ color: "#9ca3af", fontSize: 11 }}>
          grey diagonal = never measured; faded = only one study measured it
        </span>
      </span>
    </div>
  );
}

function MetricLegend({
  data,
  lowerMode = "direction",
}: {
  data: CollatedMatrixResponse;
  lowerMode?: LowerTriangleMode;
}) {
  const metrics = data.meta.metrics;
  const showInferred = useMemo(() => hasInferredCells(data), [data]);
  const showShared = useMemo(() => hasSharedCells(data), [data]);
  if (metrics.length === 0) return null;
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 22,
        alignItems: "flex-start",
        marginBottom: 18,
      }}
    >
      {metrics.some((m) => m.id === "frac_sig") && <CellKey lowerMode={lowerMode} />}
      {metrics.map((m) => {
        if (m.id === "direction_agreement" && lowerMode === "agreement") {
          return <AgreementLegend key={m.id} />;
        }
        const scale = scaleFor(m.id);
        const [lo, hi] = legendEndpoints(m.id, m.domain);
        return (
          <div
            key={m.id}
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 3,
              fontSize: 12,
              color: "#4b5563",
            }}
          >
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontWeight: 600,
                color: "#374151",
              }}
            >
              {LEGEND_TRIANGLES[m.id] && <TriangleKey points={LEGEND_TRIANGLES[m.id]} />}
              {scale.label}
            </span>
            <span
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              <span style={{ color: "#9ca3af" }}>{lo}</span>
              <span
                aria-hidden="true"
                style={{
                  display: "inline-block",
                  width: 120,
                  height: 12,
                  borderRadius: 2,
                  border: "1px solid rgba(0,0,0,0.12)",
                  background: legendGradientCss(m.id, m.domain),
                }}
              />
              <span style={{ color: "#9ca3af" }}>{hi}</span>
            </span>
            {scale.note && (
              <span style={{ color: "#9ca3af", fontSize: 11 }}>{scale.note}</span>
            )}
          </div>
        );
      })}
      {showInferred && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 3,
            fontSize: 12,
            color: "#4b5563",
            maxWidth: 300,
          }}
        >
          <span style={{ fontWeight: 600, color: "#374151" }}>
            Tested, not significant (inferred)
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span
              aria-hidden="true"
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
                width: 15,
                height: 15,
                borderRadius: 2,
                background: INFERRED_FILL,
                border: "1px solid rgba(0,0,0,0.08)",
              }}
            >
              <span
                style={{
                  width: 3,
                  height: 3,
                  borderRadius: "50%",
                  background: INFERRED_DOT,
                }}
              />
            </span>
            <span style={{ color: "#9ca3af", fontSize: 11 }}>
              Some sources publish only their significant results; where a readout
              was a hit for another perturbation in the same screen, we infer it was
              measured here too. Click a cell for the basis.
            </span>
          </span>
        </div>
      )}
      {showShared && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 3,
            fontSize: 12,
            color: "#4b5563",
            maxWidth: 300,
          }}
        >
          <span style={{ fontWeight: 600, color: "#374151" }}>Same data as another study</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span
              aria-hidden="true"
              style={{
                position: "relative",
                flexShrink: 0,
                width: 15,
                height: 15,
                borderRadius: 2,
                background: "#d1d5db",
                border: "1px solid rgba(0,0,0,0.08)",
              }}
            >
              <span
                style={{
                  position: "absolute",
                  top: 0,
                  right: 0,
                  borderStyle: "solid",
                  borderWidth: "0 6px 6px 0",
                  borderColor: `transparent ${SHARED_MARK} transparent transparent`,
                }}
              />
            </span>
            <span style={{ color: "#9ca3af", fontSize: 11 }}>
              This value also appears for this gene in another study, so it is one
              measurement published twice. Click a cell to see which study.
            </span>
          </span>
        </div>
      )}
    </div>
  );
}

const METHODS_TERM: React.CSSProperties = {
  fontWeight: 600,
  color: "#1f2937",
  marginTop: 10,
};
const METHODS_DEF: React.CSSProperties = {
  margin: "2px 0 0 0",
  color: "#4b5563",
};

/**
 * Expandable "methods" note (#216): how the matrix data is loaded, collapsed,
 * selected, and arranged — the processing behind the display, not a description
 * of the display itself. `data.meta.minSigGroupsFloor` and the columns-per-dataset
 * options are read live so the copy tracks the build instead of drifting.
 */
function MatrixMethods({ data }: { data: CollatedMatrixResponse }) {
  const m = data.meta;
  const opts = COLS_PER_DATASET_OPTIONS;
  const optsText =
    opts.length > 1
      ? `${opts.slice(0, -1).join(", ")}, or ${opts[opts.length - 1]}`
      : String(opts[0]);
  return (
    <details style={{ marginBottom: 18, maxWidth: 840 }}>
      <summary
        style={{
          cursor: "pointer",
          color: "#374151",
          fontSize: 13,
          fontWeight: 600,
          width: "fit-content",
        }}
      >
        How to read this matrix &mdash; how the data is loaded and arranged
      </summary>
      <div
        style={{
          marginTop: 8,
          padding: "12px 14px",
          background: "#f9fafb",
          border: "1px solid #e5e7eb",
          borderRadius: 8,
          fontSize: 13,
          color: "#4b5563",
          lineHeight: 1.55,
        }}
      >
        <dl style={{ margin: 0 }}>
          <dt style={{ ...METHODS_TERM, marginTop: 0 }}>Data content</dt>
          <dd style={METHODS_DEF}>
            <strong>Rows:</strong> Perturbed genes. <strong>Columns:</strong> Measured readouts. E.g., gene expression, behavioral measurements.
            A cell crossed by a grey diagonal was <strong>never measured</strong>;
            a plain pale cell <em>was</em> measured and came back near the bottom
            of its scale (e.g. a p-value at its non-significance clamp).
          </dd>

          <dt style={METHODS_TERM}>Collapsing repeated measurements</dt>
          <dd style={METHODS_DEF}>
            A single perturbed-gene &times; readout pair is sometimes measured multiple
            times within one dataset, e.g., across cell types. 
            We collapse those to one cell, keeping the{" "}
            <strong>most significant</strong>{" "}result (the smallest p-value). For
            example, the mouse cortical perturb-seq differential expression is
            measured separately in each cortical cell type; the matrix shows the
            single strongest cell type&rsquo;s result, not a per-cell-type breakdown.
          </dd>

          <dt style={METHODS_TERM}>Choosing the top columns per dataset</dt>
          <dd style={METHODS_DEF}>
            You choose how many top columns per dataset to show &mdash; {optsText}{" "}
            &mdash; with the <em>Columns per dataset</em>{" "}control.
            &ldquo;Top&rdquo; is by cross-perturbation <strong>convergence</strong>:
            a target-gene column qualifies only when it is significant (FDR &lt; 0.05)
            for at least {m.minSigGroupsFloor}{" "}distinct perturbed
            genes, then qualifying columns are ranked by how many perturbed genes
            they are significant in (most convergent first), ties broken by the
            strongest p-value, and the top N per dataset are kept. Phenotype columns
            aren&rsquo;t filtered this way &mdash; every distinct phenotype is shown.
          </dd>

          <dt style={METHODS_TERM}>The Summary view</dt>
          <dd style={METHODS_DEF}>
            <em>Summary</em>{" "}collapses each dataset to a single column, whose
            cell counts <strong>how many of that dataset&rsquo;s readouts came
            back significant</strong>{" "}for the perturbed gene. That count is
            taken over <em>every</em>{" "}readout the dataset measured &mdash; not
            just the top columns shown above, and not subject to the
            {" "}{m.minSigGroupsFloor}-perturbation convergence bar &mdash; so a
            readout that responds to only one gene still counts. It is therefore
            not the same thing as asking for one column per dataset above. The
            color is on a <strong>log scale</strong>, because the counts run from
            a handful of behavioral parameters to thousands of differentially
            expressed genes. Click a cell for the exact counts and the
            dataset&rsquo;s strongest single result. We show a count rather than a
            percentage because datasets differ in whether they store their
            non-significant readouts at all, which would make the denominators
            mean different things.
          </dd>

          <dt style={METHODS_TERM}>The &ldquo;by readout, across studies&rdquo; view</dt>
          <dd style={METHODS_DEF}>
            Pools readouts across studies so that each column is one readout,
            whichever study measured it. RNA readouts (Perturb-seq, perturb-FISH
            and expression datasets) are pooled by readout gene, matched across
            species. Phenotype readouts are pooled by ontology term (Mammalian
            and Zebrafish Phenotype Ontology, Cell Ontology): a column such as
            &ldquo;Locomotor behavior&rdquo; combines every measure the studies
            map to that term, and its label shows how many; click the label for
            the list. The unit is the <strong>study</strong>: a paper&rsquo;s
            datasets count once, and so do two papers that report the same
            experiment. A study counts as <strong>significant</strong>{" "}for a
            pair if any of its tests &mdash; any cell type, condition, method or
            pooled measure &mdash; has FDR &lt; 0.05; a cell-type-specific hit is
            a real hit. Studies that test a pair in many ways therefore get more
            chances; each study&rsquo;s tests are listed when you click a cell.
            The cell&rsquo;s upper-left triangle is{" "}<em>k</em>/<em>n</em>{" "}(of{" "}
            <em>n</em>{" "}studies that measured the pair,{" "}<em>k</em>{" "}found it
            significant); the lower-right is direction agreement among those{" "}
            <em>k</em>. For a gene column a study&rsquo;s direction is the effect
            sign at its most significant test; for a phenotype column, a study
            with significant measures in both directions counts as having no
            single direction and adds to neither side.{" "}The <strong>Lower triangle:
            Agreement</strong>{" "}switch recolors that triangle by concordance
            instead: purple where two or more significant studies agree on
            direction, orange where they disagree. Non-significant studies
            don&rsquo;t take part, since the sign of a non-significant effect is
            close to a coin flip. A significant cell with only one significant
            study gets a grey lower triangle (nothing to compare); a tile stays
            one color only when no study found the pair significant. Cells measured by a single
            study are faded, since 1 of 1 is not convergence. Studies that
            publish only their hits contribute their inferred
            tested-but-not-significant pairs to <em>n</em>{" "}(below). Phenotype
            columns come first; gene columns are ranked by how many perturbed
            genes are significant for them in two or more studies, then by total
            significant studies.
          </dd>

          <dt style={METHODS_TERM}>Sources that publish only significant results</dt>
          <dd style={METHODS_DEF}>
            Some screens publish only their hits, so an absent result could mean
            either &ldquo;tested, not significant&rdquo; or &ldquo;never
            measured&rdquo;. For pooled Perturb-seq screens we recover part of the
            difference: every perturbation is read out on the same cells, so a gene
            reported as a hit for <em>any</em>{" "}perturbation in a cell type was
            measured for every perturbation tested in that cell type. Those pairs are
            drawn as{" "}<strong>tested, not significant (inferred)</strong>{" "}and
            count toward the Summary view&rsquo;s &ldquo;measured&rdquo; totals.
            A perturbation counts as tested in a cell type only if it has at least
            one reported result there. Perturbations on the paper&rsquo;s library
            list with no reported result at all are assumed tested in every cell
            type the table covers; this is a weaker assumption and is labelled as
            such. Readouts that were never a hit anywhere stay &ldquo;no
            data&rdquo;. No p-values or effect sizes are imputed.
          </dd>

          <dt style={METHODS_TERM}>Clustering rows and columns</dt>
          <dd style={{ ...METHODS_DEF, marginBottom: 0 }}>
            By default rows are alphabetical and columns are grouped by dataset. The{" "}
            <em>Cluster</em>{" "}toggles reorder rows and/or columns so similar profiles
            sit together, computed in your browser over the currently visible
            datasets and columns. Cells at their metric&rsquo;s{" "}
            <strong>non-significance clamp</strong>{" "}(p or FDR &ge; 0.1, in either
            direction for signed effects; in the Summary view, zero significant
            readouts) are set aside first and treated like
            missing data: they are real measurements, but they all say the same
            thing &mdash; <em>nothing here</em> &mdash; and in a screen where most
            cells are non-hits they otherwise make unrelated rows look like
            perfect matches and swamp the real signal. That bites hardest where
            the widest-coverage dataset is also the emptiest: the perturb-FISH
            screen summarizes 87 of the 90 genes and finds nothing in 63 of them,
            so left in, a shared &ldquo;nothing&rdquo; there was the only thing
            most pairs of genes had in common. Effect ratios have no such
            clamp and are always kept. Each column is then min&ndash;max
            normalized over its surviving values to a common 0&ndash;1 scale (so
            &minus;log10(p), signed effects, and ratios become comparable); the
            distance between two rows (or columns) is the mean absolute
            difference over only the cells they <em>both</em>{" "}have, so the
            matrix&rsquo;s many gaps don&rsquo;t dominate; the order comes from
            average-linkage hierarchical clustering, with a fast nearest-neighbor
            fallback for very large axes. Rows left with no significant cell at
            all have nothing to be clustered on and settle in an arbitrary block.
          </dd>
        </dl>
      </div>
    </details>
  );
}

export default function MatrixPage() {
  const [mode, setMode] = useState<MatrixMode>("expanded");
  const [colsPerDataset, setColsPerDataset] = useState(25);
  const [readouts, setReadouts] = useState(100);
  // By study view: single-gene studies with several conditions as a compact
  // block (one column per condition) — the #16 prototype.
  const [compact, setCompact] = useState(false);
  // By-readout view: lower triangle shows direction (default) or agreement.
  const [lowerMode, setLowerMode] = useState<LowerTriangleMode>("direction");
  // The per-study views remember which one was last shown, so toggling the
  // collated view off returns to it.
  const [lastStudyMode, setLastStudyMode] = useState<MatrixMode>("expanded");
  const [data, setData] = useState<CollatedMatrixResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [clusterRows, setClusterRows] = useState(false);
  const [clusterCols, setClusterCols] = useState(false);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const toggleHide = (sourceTable: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(sourceTable)) next.delete(sourceTable);
      else next.add(sourceTable);
      return next;
    });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(
      `/api/collated-matrix?colsPerDataset=${colsPerDataset}&mode=${mode}` +
        `&readouts=${readouts}&compact=${compact ? 1 : 0}`
    )
      .then((res) => {
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        return res.json() as Promise<CollatedMatrixResponse>;
      })
      .then((json) => {
        if (!cancelled) {
          setData(json);
          setError(null);
        }
      })
      .catch((e: any) => {
        if (!cancelled) setError(e?.message || "Failed to load matrix");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [colsPerDataset, mode, readouts, compact]);

  const genes = data?.genes ?? [];
  const sections = data?.sections ?? [];
  const columns = data?.columns ?? [];
  const meta = data?.meta;

  const metricDomains: MetricDomains = useMemo(() => {
    const out: MetricDomains = {};
    for (const m of meta?.metrics ?? []) out[m.id] = m.domain;
    return out;
  }, [meta]);

  // Visible columns (hidden datasets dropped) then optional clustering. Row and
  // column clustering both run over the visible columns so hidden datasets are
  // excluded from the distances. Memoized so a re-render doesn't recluster.
  const visibleColumns = useMemo(
    () => columns.filter((c) => !hidden.has(c.sourceTable)),
    [columns, hidden]
  );

  const orderedColumns = useMemo(
    () =>
      clusterCols
        ? orderColumns(genes, visibleColumns).map((i) => visibleColumns[i])
        : visibleColumns,
    [clusterCols, genes, visibleColumns]
  );

  const orderedGenes = useMemo(
    () =>
      clusterRows
        ? orderRows(genes, visibleColumns).map((i) => genes[i])
        : genes,
    [clusterRows, genes, visibleColumns]
  );

  return (
    <>
      <Head>
        <title>Cross-modality matrix &mdash; SSPsyGene</title>
      </Head>
      <div
        style={{
          minHeight: "100vh",
          background: "#ffffff",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <Header />
        <main
          style={{
            // Scale the content width with the viewport (like the panel's 76vh
            // height scales with viewport height) so the matrix widens on wider
            // screens instead of being capped at a fixed 1200px. Intro text keeps
            // its own narrower max-width for readability.
            maxWidth: "94vw",
            width: "100%",
            margin: "0 auto",
            padding: "32px 16px",
            flex: 1,
          }}
        >
          <h1
            style={{
              color: "#1f2937",
              fontSize: 32,
              fontWeight: 700,
              marginBottom: 8,
            }}
          >
            Cross-modality matrix
          </h1>
          <p
            style={{
              color: "#4b5563",
              marginBottom: 16,
              lineHeight: 1.5,
              maxWidth: 840,
            }}
          >
            Every experimentally perturbed SSPsyGene target gene (rows) against{" "}
            {mode === "collated" ? "the readouts measured after perturbing it" : "each experimental dataset"}{" "}
            (columns).{" "}
            {mode === "collated" ? (
              <>
                Columns are <strong>readouts pooled across studies</strong>:
                phenotypes, then genes.
                Each cell asks: of the studies that measured this readout after
                perturbing this gene, how many found a significant change? The
                upper-left triangle shows that percentage; the lower-right shows whether
                the significant studies agree on the direction. Click a cell for
                the studies behind it.
              </>
            ) : mode === "summary" ? (
              <>
                Each dataset is collapsed to a single column, colored by{" "}
                <strong>how many of its readouts</strong>{" "}came back significant
                for that gene &mdash; counted over every readout the dataset
                measured. Click a cell for the exact counts.
              </>
            ) : (
              <>
                Each dataset fans out into its raw measurements &mdash; one
                column per measured target gene or phenotype &mdash; colored by
                its own metric (see the legends).
              </>
            )}{" "}
            Row and column gene names link to their gene search; each dataset
            heading links to its full table. The matrix is{" "}
            <strong>intentionally sparse</strong> &mdash; gaps are expected.
          </p>

          {data && <MatrixMethods data={data} />}

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
              marginBottom: 10,
            }}
          >
            <span style={{ fontSize: 13, color: "#374151", fontWeight: 600 }}>
              View:
            </span>
            <ToggleButton
              active={mode !== "collated"}
              disabled={loading}
              onClick={() => setMode(lastStudyMode)}
            >
              By study
            </ToggleButton>
            <ToggleButton
              active={mode === "collated"}
              /* Overview DBs built before the collated tables existed. */
              disabled={loading || (data != null && !data.meta.collatedAvailable)}
              onClick={() => {
                if (mode !== "collated") setLastStudyMode(mode);
                setHidden(new Set());
                setMode("collated");
              }}
            >
              By readout, across studies
            </ToggleButton>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
              marginBottom: 10,
            }}
          >
            <span style={{ fontSize: 13, color: "#374151", fontWeight: 600 }}>
              Cluster:
            </span>
            <ToggleButton
              active={clusterRows}
              disabled={loading}
              onClick={() => setClusterRows((v) => !v)}
            >
              Rows
            </ToggleButton>
            <ToggleButton
              active={clusterCols}
              disabled={loading}
              onClick={() => setClusterCols((v) => !v)}
            >
              Columns
            </ToggleButton>
            <ToggleButton
              active={false}
              disabled={hidden.size === 0}
              onClick={() => setHidden(new Set())}
            >
              Unhide all datasets
            </ToggleButton>
            {mode === "expanded" && (
              <ToggleButton
                active={compact}
                disabled={loading}
                onClick={() => setCompact((v) => !v)}
              >
                Single-gene studies as compact blocks
              </ToggleButton>
            )}
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
              marginBottom: 10,
            }}
          >
            {mode === "collated" ? (
              <>
                <span style={{ fontSize: 13, color: "#374151", fontWeight: 600 }}>
                  Readout columns:
                </span>
                {READOUT_OPTIONS.map((k) => (
                  <ToggleButton
                    key={k}
                    active={k === readouts}
                    disabled={loading}
                    onClick={() => setReadouts(k)}
                  >
                    {k}
                  </ToggleButton>
                ))}
                <span
                  style={{ fontSize: 13, color: "#374151", fontWeight: 600, marginLeft: 12 }}
                >
                  Lower triangle:
                </span>
                <ToggleButton
                  active={lowerMode === "direction"}
                  disabled={loading}
                  onClick={() => setLowerMode("direction")}
                >
                  Direction
                </ToggleButton>
                <ToggleButton
                  active={lowerMode === "agreement"}
                  disabled={loading}
                  onClick={() => setLowerMode("agreement")}
                >
                  Agreement
                </ToggleButton>
              </>
            ) : (
              <>
            <span style={{ fontSize: 13, color: "#374151", fontWeight: 600 }}>
              Columns per dataset:
            </span>
            <ToggleButton
              active={mode === "summary"}
              /* An overview DB built before #234 has no summary tables; the
                 control is disabled rather than serving an empty matrix. */
              disabled={loading || (data != null && !data.meta.summaryAvailable)}
              onClick={() => setMode("summary")}
            >
              Summary
            </ToggleButton>
            {COLS_PER_DATASET_OPTIONS.map((k) => (
              <ToggleButton
                key={k}
                active={mode === "expanded" && k === colsPerDataset}
                disabled={loading}
                onClick={() => {
                  setColsPerDataset(k);
                  setMode("expanded");
                }}
              >
                {k}
              </ToggleButton>
            ))}
              </>
            )}
          </div>

          {loading && !data && (
            <div style={{ color: "#6b7280", marginTop: 16 }}>
              Loading matrix&hellip;
            </div>
          )}

          {error && (
            <div style={{ color: "#dc2626", marginTop: 16 }}>{error}</div>
          )}

          {!error && data && genes.length === 0 && (
            <div style={{ color: "#6b7280", marginTop: 16 }}>
              No perturbed-gene data available yet.
            </div>
          )}

          {!error && data && genes.length > 0 && (
            <div
              style={{
                opacity: loading ? 0.55 : 1,
                pointerEvents: loading ? "none" : "auto",
                transition: "opacity 0.15s",
              }}
            >
              <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 6 }}>
                {orderedGenes.length.toLocaleString()} perturbed genes &times;{" "}
                {orderedColumns.length.toLocaleString()}{" "}
                {mode === "summary"
                  ? "datasets"
                  : mode === "collated"
                    ? `readouts, pooled over ${meta?.collatedStudies?.length ?? 0} studies`
                    : "columns"}
                {mode === "collated" &&
                  (meta?.collatedStudiesInSeveralSections?.length ?? 0) > 0 && (
                    <span>
                      {" "}
                      ({meta!.collatedStudiesInSeveralSections!.join(", ")}{" "}
                      {meta!.collatedStudiesInSeveralSections!.length === 1 ? "contributes" : "contribute"}{" "}
                      to more than one section, so the section counts add up to more)
                    </span>
                  )}
                {hidden.size > 0 && (
                  <span style={{ color: "#9ca3af" }}>
                    {" "}
                    &mdash; {hidden.size} dataset{hidden.size === 1 ? "" : "s"} hidden
                  </span>
                )}
                {mode === "expanded" && meta?.expandedColumnsTruncated && (
                  <span style={{ color: "#9ca3af" }}>
                    {" "}
                    &mdash; top {meta.colsPerDataset} per dataset shown
                  </span>
                )}
                {" "}
                <span style={{ color: "#111827", fontWeight: 700 }}>
                  &mdash; click any cell for its value
                </span>
              </div>
              {data && (
                <MetricLegend data={data} lowerMode={mode === "collated" ? lowerMode : "direction"} />
              )}
              <CollatedMatrix
                sections={sections}
                columns={orderedColumns}
                genes={orderedGenes}
                metricDomains={metricDomains}
                bandsVisible={mode === "summary" ? false : !clusterCols}
                summary={mode === "summary"}
                lowerMode={mode === "collated" ? lowerMode : "direction"}
                onToggleHide={toggleHide}
              />
            </div>
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}
