import { useEffect, useState } from "react";
import Head from "next/head";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import CollatedMatrix, {
  StatusSwatch,
  pColor,
} from "@/components/CollatedMatrix";
import type {
  CellStatus,
  CollatedMatrixResponse,
} from "@/lib/collated-matrix-types";

const STATUS_LEGEND: [CellStatus, string][] = [
  ["significant", "significant"],
  ["data", "data, not significant"],
  ["assayed_null", "assayed but null"],
  ["none", "no data"],
];

const COLS_PER_DATASET_OPTIONS = [25, 50, 100, 200];

function pvalueRampCss(): string {
  const stops = [1, 4.75, 9.5, 14.25, 20]
    .map((v) => `${pColor(v)} ${(((v - 1) / 19) * 100).toFixed(0)}%`)
    .join(", ");
  return `linear-gradient(to right, ${stops})`;
}

function Legend() {
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 18,
        alignItems: "center",
        fontSize: 13,
        color: "#4b5563",
        marginBottom: 18,
      }}
    >
      <span style={{ fontWeight: 600, color: "#374151" }}>Status columns:</span>
      {STATUS_LEGEND.map(([status, label]) => (
        <span
          key={status}
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <StatusSwatch status={status} /> {label}
        </span>
      ))}
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          marginLeft: 8,
        }}
      >
        <span style={{ fontWeight: 600, color: "#374151" }}>
          Expanded columns:
        </span>
        <span>-log10(p)</span>
        <span style={{ color: "#9ca3af" }}>1</span>
        <span
          aria-hidden="true"
          style={{
            display: "inline-block",
            width: 90,
            height: 12,
            borderRadius: 2,
            border: "1px solid rgba(0,0,0,0.12)",
            background: pvalueRampCss(),
          }}
        />
        <span style={{ color: "#9ca3af" }}>20</span>
        <span style={{ color: "#9ca3af" }}>(perturb-FISH: qval)</span>
      </span>
    </div>
  );
}

export default function MatrixPage() {
  const [colsPerDataset, setColsPerDataset] = useState(25);
  const [data, setData] = useState<CollatedMatrixResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
  const expanded = columns.filter((c) => c.kind === "pvalue").length;

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
            each experimental modality (grouped columns). Most modalities are a
            single <strong>color-coded status</strong> tile; RNA expression,
            perturb-seq, and perturb-FISH are <strong>fanned out</strong> into
            one column per measured target gene (grouped by source dataset),
            colored by <strong>-log10(p)</strong> (red = most significant). The
            matrix is <strong>intentionally sparse</strong> &mdash; gaps are
            expected.
          </p>

          <Legend />

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
              {genes.length.toLocaleString()} perturbed genes ×{" "}
              {columns.length.toLocaleString()} columns
              {expanded > 0 &&
                ` (${expanded.toLocaleString()} expanded target-gene columns)`}
              {meta?.expandedColumnsTruncated && (
                <span style={{ color: "#9ca3af" }}>
                  {" "}
                  — top {meta.colsPerDataset} per dataset shown
                </span>
              )}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                style={{ fontSize: 13, color: "#374151", fontWeight: 600 }}
              >
                Columns per dataset:
              </span>
              {COLS_PER_DATASET_OPTIONS.map((k) => {
                const active = k === colsPerDataset;
                return (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setColsPerDataset(k)}
                    aria-pressed={active}
                    disabled={loading}
                    style={{
                      padding: "4px 10px",
                      background: active ? "#e5e7eb" : "#ffffff",
                      border: "1px solid #d1d5db",
                      color: "#1f2937",
                      borderRadius: 6,
                      cursor: active || loading ? "default" : "pointer",
                      fontSize: 13,
                      fontWeight: active ? 700 : 500,
                    }}
                  >
                    {k}
                  </button>
                );
              })}
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
                columns={columns}
                genes={genes}
              />
            </div>
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}
