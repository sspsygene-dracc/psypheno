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
 * Expandable "methods" note (#216): explains exactly which rows and columns the
 * matrix shows, and how columns are selected. Numbers come from `data.meta` so
 * the copy tracks the live build instead of drifting from hardcoded values.
 */
function MatrixMethods({ data }: { data: CollatedMatrixResponse }) {
  const m = data.meta;
  const metricList = m.metrics.map((mp) => scaleFor(mp.id).label).join(", ");
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
        How to read this matrix &mdash; what the rows and columns are
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
          <dt style={{ ...METHODS_TERM, marginTop: 0 }}>Rows &mdash; perturbed genes</dt>
          <dd style={METHODS_DEF}>
            Every experimentally perturbed SSPsyGene target gene, one row per gene,
            pooled across all included datasets.
          </dd>

          <dt style={METHODS_TERM}>Columns &mdash; one per measured readout</dt>
          <dd style={METHODS_DEF}>
            Each dataset fans out into one sub-column per measurement: a{" "}
            <strong>target gene</strong> (gene columns) or a{" "}
            <strong>phenotype</strong> (behavioral parameter, brain region, cell
            subcluster). Columns are grouped by dataset unless you cluster them.
          </dd>

          <dt style={METHODS_TERM}>Which datasets</dt>
          <dd style={METHODS_DEF}>
            Only grant-verified <strong>SSPsyGene consortium</strong>{" "}
            datasets appear &mdash; a dataset is included only when its paper
            acknowledges an SSPsyGene consortium grant.
          </dd>

          <dt style={METHODS_TERM}>How columns are chosen</dt>
          <dd style={METHODS_DEF}>
            A target-gene column is shown only when it is significant across at
            least <strong>{m.minSigGroupsFloor}</strong> distinct perturbed genes
            (phenotype columns are always kept). At most{" "}
            <strong>{m.colsPerDataset}</strong>{" "}
            columns per dataset are shown &mdash; change this with the{" "}
            <em>Columns per dataset</em> control (up to{" "}
            {m.materializeTopM} are precomputed).
            {m.expandedColumnsTruncated && (
              <>
                {" "}
                Some datasets have more eligible columns than shown (
                {m.expandedColumnsAvailable.toLocaleString()} available across all
                datasets); only the most convergent are displayed.
              </>
            )}
          </dd>

          <dt style={METHODS_TERM}>Color</dt>
          <dd style={METHODS_DEF}>
            Each column is colored by its own metric
            {metricList ? ` (${metricList})` : ""}; metrics are never mixed in one
            scale &mdash; see the legends above.
          </dd>

          <dt style={METHODS_TERM}>Sparsity</dt>
          <dd style={{ ...METHODS_DEF, marginBottom: 0 }}>
            The matrix is intentionally sparse; an empty cell means there is no
            measurement for that perturbed-gene &times; readout pair. Gaps are
            expected and permanent.
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
