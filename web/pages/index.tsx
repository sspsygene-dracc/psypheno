import { useEffect, useState } from "react";
import Head from "next/head";
import SearchBar, { SearchSuggestion } from "@/components/SearchBar";
import GeneResults from "@/components/GeneResults";

type TableResult = {
  tableName: string;
  displayColumns: string[];
  rows: Record<string, unknown>[];
};

export default function Home() {
  const [selected, setSelected] = useState<SearchSuggestion | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<TableResult[]>([]);

  useEffect(() => {
    const fetchData = async () => {
      if (!selected) return;
      setLoading(true);
      setError(null);
      setData([]);
      try {
        const res = await fetch("/api/gene-data", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entrezId: selected.entrezId }),
        });
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const payload = await res.json();
        setData(Array.isArray(payload.results) ? payload.results : []);
      } catch (e: any) {
        setError(e?.message || "Failed to load data");
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [selected]);

  return (
    <>
      <Head>
        <title>SSPsyGene Demo</title>
      </Head>
      <div style={{ minHeight: "100vh", background: "#0b1220" }}>
        <header
          style={{
            padding: "32px 16px",
            textAlign: "center",
            color: "#f1f5f9",
            fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
          }}
        >
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 16 }}>
            <img
              src="/1763-ssPsyGeneLogo_v2_A.png"
              alt="SSPsyGene Logo"
              style={{
                width: "min(240px, 60%)",
                height: "auto",
                filter: "drop-shadow(0 4px 10px rgba(0,0,0,0.35))",
                borderRadius: 12,
              }}
            />
          </div>
          <p style={{ opacity: 0.85, marginTop: 8 }}>
            Explore cross-species datasets from the SSPsyGene project
          </p>
        </header>
        <main style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <div style={{ width: "min(720px, 92%)" }}>
            <SearchBar
              placeholder="Search for a gene (e.g., CTNNB1, SATB1)"
              onSelect={(s) => setSelected(s)}
            />
          </div>
          <div style={{ width: "100%" }}>
            {selected && (
              <div style={{ width: "100%" }}>
                {loading && (
                  <div style={{ color: "#e5e7eb", textAlign: "center", marginTop: 16 }}>
                    Loading data...
                  </div>
                )}
                {error && (
                  <div style={{ color: "#ef4444", textAlign: "center", marginTop: 16 }}>
                    {error}
                  </div>
                )}
                {!loading && !error && (
                  <GeneResults entrezId={selected.entrezId} data={data} />)
                }
              </div>
            )}
          </div>
        </main>
      </div>
    </>
  );
}
