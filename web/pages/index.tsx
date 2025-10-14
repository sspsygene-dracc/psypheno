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
  const [perturbed, setPerturbed] = useState<SearchSuggestion | null>(null);
  const [target, setTarget] = useState<SearchSuggestion | null>(null);
  const [searchMode, setSearchMode] = useState<"general" | "pair">("general");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [generalData, setGeneralData] = useState<TableResult[]>([]);
  const [pairData, setPairData] = useState<TableResult[]>([]);

  useEffect(() => {
    const fetchData = async () => {
      if (!selected) return;
      setLoading(true);
      setError(null);
      setGeneralData([]);
      try {
        const res = await fetch("/api/gene-data", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entrezId: selected.entrezId }),
        });
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const payload = await res.json();
        console.log("gene-data payload", payload);
        const results = Array.isArray(payload.results) ? payload.results : [];
        console.log("Setting data to:", results);
        setGeneralData(results);
      } catch (e: any) {
        setError(e?.message || "Failed to load data");
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [selected]);

  // Fetch pair data when both perturbed and target are selected in pair mode
  useEffect(() => {
    const fetchPair = async () => {
      if (searchMode !== "pair") return;
      if (!perturbed && !target) return;
      setLoading(true);
      setError(null);
      setPairData([]);
      try {
        const res = await fetch("/api/gene-pair-data", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            perturbedEntrezId: perturbed?.entrezId || null,
            targetEntrezId: target?.entrezId || null,
          }),
        });
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const payload = await res.json();
        console.log("gene-pair-data payload", payload);
        const results = Array.isArray(payload.results) ? payload.results : [];
        console.log("Setting pair data to:", results);
        setPairData(results);
      } catch (e: any) {
        setError(e?.message || "Failed to load data");
      } finally {
        setLoading(false);
      }
    };
    fetchPair();
  }, [perturbed, target]);

  const displayResults = () => {
    if (searchMode === "general" && selected) {
      return true;
    }
    if (searchMode === "pair" && (perturbed || target)) {
      return true;
    }
    return false;
  };

  const displayEntrezId = () => {
    if (searchMode === "general" && selected) {
      return selected.entrezId;
    }
    if (searchMode === "pair" && (perturbed || target)) {
      return `Perturbed: ${perturbed?.name || "Any"} → Target: ${
        target?.name || "Any"
      }`;
    }
    return null;
  };

  const maybeLoading = (
    <>
      {loading && (
        <div
          style={{
            color: "#e5e7eb",
            textAlign: "center",
            marginTop: 16,
          }}
        >
          Loading data...
        </div>
      )}
      {error && (
        <div
          style={{
            color: "#ef4444",
            textAlign: "center",
            marginTop: 16,
          }}
        >
          {error}
        </div>
      )}
    </>
  );

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
            fontFamily:
              "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              marginBottom: 16,
            }}
          >
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
        <main
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
          }}
        >
          {/* Mode toggle */}
          <div
            style={{
              width: "min(720px, 92%)",
              boxSizing: "border-box",
              display: "flex",
              gap: 8,
              background: "#0f172a",
              border: "1px solid #334155",
              borderRadius: 12,
              padding: 4,
            }}
          >
            <button
              onClick={() => setSearchMode("general")}
              style={{
                flex: 1,
                padding: "10px 12px",
                borderRadius: 10,
                border: "none",
                cursor: "pointer",
                background:
                  searchMode === "general" ? "#1e293b" : "transparent",
                color: "#e5e7eb",
                fontWeight: 600,
              }}
            >
              General gene search
            </button>
            <button
              onClick={() => setSearchMode("pair")}
              style={{
                flex: 1,
                padding: "10px 12px",
                borderRadius: 10,
                border: "none",
                cursor: "pointer",
                background: searchMode === "pair" ? "#1e293b" : "transparent",
                color: "#e5e7eb",
                fontWeight: 600,
              }}
            >
              Perturbed/Target search
            </button>
          </div>

          {searchMode === "general" && (
            <div
              style={{
                width: "min(720px, 92%)",
                boxSizing: "border-box",
                marginTop: 16,
                background: "#0f172a",
                border: "1px solid #334155",
                borderRadius: 12,
                padding: 4,
              }}
            >
              <SearchBar
                placeholder="Search for a gene (e.g., CTNNB1, SATB1)"
                onSelect={(s) => setSelected(s)}
                value={selected}
              />
            </div>
          )}

          {searchMode === "pair" && (
            <div
              style={{
                width: "min(720px, 92%)",
                boxSizing: "border-box",
                marginTop: 16,
                background: "#0f172a",
                border: "1px solid #334155",
                borderRadius: 12,
                padding: 4,
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 12,
              }}
            >
              <SearchBar
                placeholder="Perturbed gene"
                onSelect={(s) => setPerturbed(s)}
                value={perturbed}
              />
              <SearchBar
                placeholder="Target gene"
                onSelect={(s) => setTarget(s)}
                value={target}
              />
            </div>
          )}
          <div style={{ width: "100%" }}>
            {displayResults() && (
              <div style={{ width: "100%" }}>
                {maybeLoading}
                {!loading && !error && (
                  <GeneResults
                    entrezId={displayEntrezId()}
                    data={searchMode === "general" ? generalData : pairData}
                  />
                )}
              </div>
            )}
          </div>
        </main>
      </div>
    </>
  );
}
