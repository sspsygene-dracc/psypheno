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
            maxWidth: "1200px",
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

          {data && <MetricLegend data={data} />}

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
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                flexWrap: "wrap",
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
              <span
                style={{
                  fontSize: 13,
                  color: "#374151",
                  fontWeight: 600,
                  marginLeft: 8,
                }}
              >
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
