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

// A yellow→orange→red gradient bar matching the p-value tiles' ramp.
function pvalueRampCss(): string {
  const stops = [1, 4.75, 9.5, 14.25, 20]
    .map((v) => {
      const t = ((v - 1) / 19) * 100;
      return `${pColor(v)} ${t.toFixed(0)}%`;
    })
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
        marginBottom: 20,
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
          RNA expression:
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
      </span>
    </div>
  );
}

export default function MatrixPage() {
  const [data, setData] = useState<CollatedMatrixResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchMatrix = async () => {
      try {
        const res = await fetch("/api/collated-matrix");
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const json = (await res.json()) as CollatedMatrixResponse;
        setData(json);
      } catch (e: any) {
        setError(e?.message || "Failed to load matrix");
      } finally {
        setLoading(false);
      }
    };
    fetchMatrix();
  }, []);

  const genes = data?.genes ?? [];
  const sections = data?.sections ?? [];
  const columns = data?.columns ?? [];
  const meta = data?.meta;

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
              maxWidth: 820,
            }}
          >
            Every experimentally perturbed SSPsyGene target gene (rows) against
            each experimental modality (grouped columns). Most modalities are a
            single <strong>color-coded status</strong> tile; RNA expression is{" "}
            <strong>fanned out</strong> into one column per measured target gene
            that responds across multiple perturbations, colored by{" "}
            <strong>-log10(p)</strong> (red = most significant). The matrix is{" "}
            <strong>intentionally sparse</strong> &mdash; gaps are expected.
          </p>

          <Legend />

          {loading && (
            <div style={{ color: "#6b7280", marginTop: 16 }}>
              Loading matrix&hellip;
            </div>
          )}

          {error && (
            <div style={{ color: "#dc2626", marginTop: 16 }}>{error}</div>
          )}

          {!loading && !error && genes.length === 0 && (
            <div style={{ color: "#6b7280", marginTop: 16 }}>
              No perturbed-gene data available yet.
            </div>
          )}

          {!loading && !error && genes.length > 0 && (
            <>
              <CollatedMatrix
                sections={sections}
                columns={columns}
                genes={genes}
              />
              {meta?.expressionColumnsTruncated && (
                <div style={{ color: "#9ca3af", fontSize: 12, marginTop: 8 }}>
                  Showing the {meta.expressionColumnCount.toLocaleString()}{" "}
                  strongest of {meta.expressionColumnsAvailable.toLocaleString()}{" "}
                  qualifying RNA-expression columns.
                </div>
              )}
            </>
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}
