import { useEffect, useState } from "react";
import Head from "next/head";
import Link from "next/link";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

type Gene = {
  entrezId: number;
  name: string;
  species: string;
  datasetCount: number;
};

export default function AllGenes() {
  const [genes, setGenes] = useState<Gene[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    const fetchGenes = async () => {
      try {
        const res = await fetch("/api/all-genes");
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const data = await res.json();
        setGenes(data.genes);
      } catch (e: any) {
        setError(e?.message || "Failed to load genes");
      } finally {
        setLoading(false);
      }
    };
    fetchGenes();
  }, []);

  const filteredGenes = genes.filter((gene) =>
    gene.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <>
      <Head>
        <title>All Genes - SSPsyGene</title>
      </Head>
      <div
        style={{
          minHeight: "100vh",
          background: "#0b1220",
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
              color: "#f1f5f9",
              fontSize: 32,
              fontWeight: 700,
              marginBottom: 8,
            }}
          >
            All Genes
          </h1>
          <p style={{ color: "#94a3b8", marginBottom: 24 }}>
            Browse all genes across datasets with their occurrence counts
          </p>

          {loading && (
            <div style={{ color: "#e5e7eb", textAlign: "center", marginTop: 32 }}>
              Loading genes...
            </div>
          )}

          {error && (
            <div style={{ color: "#ef4444", textAlign: "center", marginTop: 32 }}>
              {error}
            </div>
          )}

          {!loading && !error && (
            <>
              <div style={{ marginBottom: 24 }}>
                <input
                  type="text"
                  placeholder="Search genes..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  style={{
                    width: "100%",
                    padding: "12px 16px",
                    background: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: 8,
                    color: "#e5e7eb",
                    fontSize: 16,
                  }}
                />
              </div>

              <div
                style={{
                  background: "#0f172a",
                  border: "1px solid #334155",
                  borderRadius: 12,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 150px 100px",
                    padding: "16px",
                    background: "#1e293b",
                    color: "#94a3b8",
                    fontWeight: 600,
                    fontSize: 14,
                  }}
                >
                  <div>Gene Name</div>
                  <div>Species</div>
                  <div style={{ textAlign: "right" }}>Datasets</div>
                </div>

                <div style={{ maxHeight: "calc(100vh - 400px)", overflowY: "auto" }}>
                  {filteredGenes.length === 0 ? (
                    <div
                      style={{
                        padding: 32,
                        textAlign: "center",
                        color: "#94a3b8",
                      }}
                    >
                      No genes found
                    </div>
                  ) : (
                    filteredGenes.map((gene, idx) => (
                      <Link
                        key={`${gene.entrezId}-${idx}`}
                        href={`/?gene=${gene.entrezId}`}
                        style={{
                          display: "grid",
                          gridTemplateColumns: "1fr 150px 100px",
                          padding: "16px",
                          borderTop: "1px solid #334155",
                          color: "#e5e7eb",
                          textDecoration: "none",
                          transition: "background 0.2s ease",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "#1e293b";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "transparent";
                        }}
                      >
                        <div style={{ fontWeight: 500 }}>{gene.name}</div>
                        <div style={{ color: "#94a3b8", textTransform: "capitalize" }}>
                          {gene.species}
                        </div>
                        <div style={{ textAlign: "right", color: "#60a5fa" }}>
                          {gene.datasetCount}
                        </div>
                      </Link>
                    ))
                  )}
                </div>
              </div>

              <div style={{ marginTop: 16, color: "#94a3b8", fontSize: 14 }}>
                Showing {filteredGenes.length} of {genes.length} genes
              </div>
            </>
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}

