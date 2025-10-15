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

type ApiResponse = {
  genes: Gene[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  query: string;
};

export default function AllGenes() {
  const [genes, setGenes] = useState<Gene[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);

  // Debounce the search term
  useEffect(() => {
    const id = setTimeout(() => setDebounced(searchTerm), 350);
    return () => clearTimeout(id);
  }, [searchTerm]);

  // Reset to first page when search changes
  useEffect(() => {
    setPage(1);
  }, [debounced]);

  // Fetch when page or search changes
  useEffect(() => {
    const controller = new AbortController();
    const fetchGenes = async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        params.set("page", String(page));
        params.set("pageSize", String(pageSize));
        if (debounced.trim().length > 0) params.set("q", debounced.trim());
        const res = await fetch(`/api/all-genes?${params.toString()}`, {
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const data: ApiResponse = await res.json();
        setGenes(data.genes);
        setTotal(data.total);
        setTotalPages(data.totalPages);
      } catch (e: any) {
        if (e.name !== "AbortError") {
          setError(e?.message || "Failed to load genes");
        }
      } finally {
        setLoading(false);
      }
    };
    fetchGenes();
    return () => controller.abort();
  }, [page, pageSize, debounced]);

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
                    outline: "none",
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
                  {genes.length === 0 ? (
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
                    genes.map((gene, idx) => (
                      <Link
                        key={`${gene.entrezId}-${idx}`}
                        href={`/?searchMode=general&selected=${gene.name}`}
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
                        <div style={{ textAlign: "right", color: "#94a3b8" }}>
                          {gene.datasetCount}
                        </div>
                      </Link>
                    ))
                  )}
                </div>
              </div>

              <div style={{ marginTop: 16, color: "#94a3b8", fontSize: 14 }}>
                Showing page {page} of {totalPages} · {total} total genes
              </div>

              <div
                style={{
                  marginTop: 12,
                  display: "flex",
                  gap: 8,
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1 || loading}
                    style={{
                      padding: "8px 12px",
                      background: page <= 1 || loading ? "#0f172a" : "#1e293b",
                      border: "1px solid #334155",
                      color: "#e5e7eb",
                      borderRadius: 8,
                      cursor: page <= 1 || loading ? "not-allowed" : "pointer",
                    }}
                  >
                    Prev
                  </button>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages || loading}
                    style={{
                      padding: "8px 12px",
                      background:
                        page >= totalPages || loading ? "#0f172a" : "#1e293b",
                      border: "1px solid #334155",
                      color: "#e5e7eb",
                      borderRadius: 8,
                      cursor:
                        page >= totalPages || loading ? "not-allowed" : "pointer",
                    }}
                  >
                    Next
                  </button>
                </div>

                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ color: "#94a3b8" }}>Rows per page</span>
                  <select
                    value={pageSize}
                    onChange={(e) => setPageSize(parseInt(e.target.value, 10))}
                    disabled={loading}
                    style={{
                      padding: "8px 12px",
                      background: "#0f172a",
                      border: "1px solid #334155",
                      color: "#e5e7eb",
                      borderRadius: 8,
                    }}
                  >
                    <option value={25}>25</option>
                    <option value={50}>50</option>
                    <option value={100}>100</option>
                    <option value={200}>200</option>
                  </select>
                </div>
              </div>
            </>
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}

