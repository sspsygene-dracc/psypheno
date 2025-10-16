import { useEffect, useState, useRef } from "react";
import Head from "next/head";
import { useRouter } from "next/router";
import SearchBar from "@/components/SearchBar";
import GeneResults from "@/components/GeneResults";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { TableResult } from "@/lib/table_result";
import { SearchSuggestion } from "@/lib/suggestions";

export default function Home() {
  const router = useRouter();
  const [selected, setSelected] = useState<SearchSuggestion | null>(null);
  const [perturbed, setPerturbed] = useState<SearchSuggestion | null>(null);
  const [target, setTarget] = useState<SearchSuggestion | null>(null);
  const [searchMode, setSearchMode] = useState<"general" | "pair">("general");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [generalData, setGeneralData] = useState<TableResult[]>([]);
  const [pairData, setPairData] = useState<TableResult[]>([]);
  const hydratedFromQuery = useRef<boolean>(false);

  // Resolve a gene symbol to a SearchSuggestion via the search API
  const resolveSymbol = async (
    symbol: string
  ): Promise<SearchSuggestion | null> => {
    try {
      const res = await fetch("/api/search-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: symbol }),
      });
      if (!res.ok) return null;
      const data = (await res.json()) as {
        suggestions: SearchSuggestion[];
        searchText: string;
      };
      const suggestions: SearchSuggestion[] = Array.isArray(data.suggestions)
        ? data.suggestions
        : [];
      const exact = suggestions.find((s) => s.humanSymbol === symbol);
      return exact || suggestions[0] || null;
    } catch (_) {
      return null;
    }
  };

  // Initialize state from URL query on first ready
  useEffect(() => {
    if (!router.isReady || hydratedFromQuery.current) return;
    const q = router.query || {};
    const qMode = (q.searchmode as string) === "pair" ? "pair" : "general";
    setSearchMode(qMode);

    const hydrate = async () => {
      if (qMode === "general") {
        const sel = typeof q.selected === "string" ? q.selected : undefined;
        if (sel) {
          const s = await resolveSymbol(sel);
          if (s) setSelected(s);
        }
      } else {
        const p = typeof q.perturbed === "string" ? q.perturbed : undefined;
        const t = typeof q.target === "string" ? q.target : undefined;
        if (p) {
          const sp = await resolveSymbol(p);
          if (sp) setPerturbed(sp);
        }
        if (t) {
          const st = await resolveSymbol(t);
          if (st) setTarget(st);
        }
      }
      hydratedFromQuery.current = true;
    };
    hydrate();
  }, [router.isReady]);

  // Keep URL in sync with UI state
  useEffect(() => {
    if (!router.isReady) return;
    // Avoid pushing while we're still hydrating initial state
    if (!hydratedFromQuery.current) return;

    const nextQuery: Record<string, string> = { searchmode: searchMode };
    if (searchMode === "general") {
      if (selected?.humanSymbol) nextQuery.selected = selected.humanSymbol;
    } else {
      if (perturbed?.humanSymbol) nextQuery.perturbed = perturbed.humanSymbol;
      if (target?.humanSymbol) nextQuery.target = target.humanSymbol;
    }

    // Compare with current to avoid unnecessary replaces
    const curr = router.query as Record<string, any>;
    const keys = new Set([...Object.keys(curr), ...Object.keys(nextQuery)]);
    let changed = false;
    for (const k of keys) {
      const a = curr[k];
      const b = nextQuery[k];
      if ((a ?? undefined) !== (b ?? undefined)) {
        changed = true;
        break;
      }
    }
    if (!changed) return;

    router.replace({ pathname: router.pathname, query: nextQuery }, undefined, {
      shallow: true,
    });
  }, [searchMode, selected, perturbed, target, router.isReady]);

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
          body: JSON.stringify({ centralGeneId: selected.centralGeneId }),
        });
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const payload = await res.json();
        const results = Array.isArray(payload.results) ? payload.results : [];
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
            perturbedCentralGeneId: perturbed?.centralGeneId || null,
            targetCentralGeneId: target?.centralGeneId || null,
          }),
        });
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const payload = await res.json();
        const results = Array.isArray(payload.results) ? payload.results : [];
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

  const displayGeneString = () => {
    if (searchMode === "general" && selected) {
      return `${selected.humanSymbol}`;
    }
    if (searchMode === "pair" && (perturbed || target)) {
      return `perturbed ${perturbed?.humanSymbol || "Any"} → target ${
        target?.humanSymbol || "Any"
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
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            padding: "32px 16px",
            flex: 1,
          }}
        >
          <div
            style={{
              textAlign: "center",
              color: "#f1f5f9",
              marginBottom: 32,
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
          </div>
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
                    entrezId={displayGeneString()}
                    data={searchMode === "general" ? generalData : pairData}
                  />
                )}
              </div>
            )}
          </div>
        </main>
        <Footer />
      </div>
    </>
  );
}
