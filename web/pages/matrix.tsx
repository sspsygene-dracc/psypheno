import { useEffect, useMemo, useState } from "react";
import Head from "next/head";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import CollatedMatrix, { type MetricDomains } from "@/components/CollatedMatrix";
import {
  legendEndpoints,
  legendGradientCss,
  scaleFor,
} from "@/lib/matrix-color-scales";
import { orderColumns, orderRows } from "@/lib/matrix-clustering";
import type { CollatedMatrixResponse } from "@/lib/collated-matrix-types";

const COLS_PER_DATASET_OPTIONS = [25, 50, 100, 200];

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

function MetricLegend({ data }: { data: CollatedMatrixResponse }) {
  const metrics = data.meta.metrics;
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
      {metrics.map((m) => {
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
            <span style={{ fontWeight: 600, color: "#374151" }}>{scale.label}</span>
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

          <dt style={METHODS_TERM}>Clustering rows and columns</dt>
          <dd style={{ ...METHODS_DEF, marginBottom: 0 }}>
            By default rows are alphabetical and columns are grouped by dataset. The{" "}
            <em>Cluster</em>{" "}toggles reorder rows and/or columns so similar profiles
            sit together, computed in your browser over the currently visible
            datasets and columns. Cells at their metric&rsquo;s{" "}
            <strong>non-significance clamp</strong>{" "}(p or FDR &ge; 0.1, in either
            direction for signed effects) are set aside first and treated like
            missing data: they are real measurements, but they all say the same
            thing &mdash; <em>nothing here</em> &mdash; and in a screen where most
            cells are non-hits they otherwise make unrelated rows look like
            perfect matches and swamp the real signal. Effect ratios have no such
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
  const [colsPerDataset, setColsPerDataset] = useState(25);
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
    fetch(`/api/collated-matrix?colsPerDataset=${colsPerDataset}`)
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
  }, [colsPerDataset]);

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
            Every experimentally perturbed SSPsyGene target gene (rows) against
            each experimental dataset (grouped columns). Each dataset fans out
            into its raw measurements &mdash; one column per measured target gene
            or phenotype &mdash; colored by its own metric (see the legends). Row
            and column gene names link to their gene search; each dataset heading
            links to its full table. The matrix is{" "}
            <strong>intentionally sparse</strong> &mdash; gaps are expected.
          </p>

          {data && <MatrixMethods data={data} />}

          {data && <MetricLegend data={data} />}

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
              Columns per dataset:
            </span>
            {COLS_PER_DATASET_OPTIONS.map((k) => (
              <ToggleButton
                key={k}
                active={k === colsPerDataset}
                disabled={loading}
                onClick={() => setColsPerDataset(k)}
              >
                {k}
              </ToggleButton>
            ))}
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
                {orderedColumns.length.toLocaleString()} columns
                {hidden.size > 0 && (
                  <span style={{ color: "#9ca3af" }}>
                    {" "}
                    &mdash; {hidden.size} dataset{hidden.size === 1 ? "" : "s"} hidden
                  </span>
                )}
                {meta?.expandedColumnsTruncated && (
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
              <CollatedMatrix
                sections={sections}
                columns={orderedColumns}
                genes={orderedGenes}
                metricDomains={metricDomains}
                bandsVisible={!clusterCols}
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
