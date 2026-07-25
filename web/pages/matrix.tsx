import { useEffect, useState } from "react";
import Head from "next/head";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import CollatedMatrix, {
  StatusSwatch,
  type MatrixGeneRow,
  type MatrixModalityColumn,
} from "@/components/CollatedMatrix";
import type { CellStatus } from "@/pages/api/collated-matrix";

interface MatrixResponse {
  modalities: MatrixModalityColumn[];
  genes: MatrixGeneRow[];
}

const LEGEND_ITEMS: [CellStatus, string][] = [
  ["significant", "significant"],
  ["data", "data, not significant"],
  ["assayed_null", "assayed but null"],
  ["none", "no data"],
];

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
      <span style={{ fontWeight: 600, color: "#374151" }}>Legend:</span>
      {LEGEND_ITEMS.map(([status, label]) => (
        <span
          key={status}
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <StatusSwatch status={status} /> {label}
        </span>
      ))}
    </div>
  );
}

export default function MatrixPage() {
  const [data, setData] = useState<MatrixResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchMatrix = async () => {
      try {
        const res = await fetch("/api/collated-matrix");
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const json = (await res.json()) as MatrixResponse;
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
  const modalities = data?.modalities ?? [];

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
              maxWidth: 760,
            }}
          >
            Every experimentally perturbed SSPsyGene target gene (rows) against
            each experimental modality (columns). Each tile is a{" "}
            <strong>color-coded status</strong>, not an effect size. The matrix
            is <strong>intentionally sparse</strong> &mdash; most modalities have
            little or no data yet, and gaps are expected.
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
            <CollatedMatrix modalities={modalities} genes={genes} />
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}
