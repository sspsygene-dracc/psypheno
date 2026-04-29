import { useEffect, useState, useRef } from "react";
import Head from "next/head";
import { useRouter } from "next/router";
import SearchBar from "@/components/SearchBar";
import GeneResults from "@/components/GeneResults";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { TableResult } from "@/lib/table_result";
import { SearchSuggestion } from "@/state/SearchSuggestion";

export default function Home() {
  const router = useRouter();
  const [selected, setSelected] = useState<SearchSuggestion | null>(null);
  const [perturbed, setPerturbed] = useState<SearchSuggestion | null>(null);
  const [target, setTarget] = useState<SearchSuggestion | null>(null);
  const [searchMode, setSearchMode] = useState<"general" | "pair">("general");
  const [direction, setDirection] = useState<"target" | "perturbed">("target");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [generalData, setGeneralData] = useState<TableResult[]>([]);
  const [pairData, setPairData] = useState<TableResult[]>([]);
  const [assayTypeLabels, setAssayTypeLabels] = useState<
    Record<string, string>
  >({});
  const [geneDescription, setGeneDescription] = useState<string | null>(null);
  const [llmResult, setLlmResult] = useState<{
    pubmedLinks: string | null;
    summary: string | null;
    status: string;
    searchDate: string;
  } | null>(null);
  const hydratedFromQuery = useRef<boolean>(false);

  useEffect(() => {
    fetch("/api/assay-types")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.assayTypes) setAssayTypeLabels(data.assayTypes);
      })
      .catch(() => {});
  }, []);

  // Resolve a gene symbol to a SearchSuggestion via the search API
  const resolveSymbol = async (
    symbol: string,
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

  // Sync state from URL: runs on initial ready and whenever query params
  // change externally (e.g. clicking a gene-cell Link in a result table or
  // navigating via Back/Forward). Idempotent — skips re-resolving when the
  // current state already matches the URL.
  const qSelected =
    typeof router.query.selected === "string" ? router.query.selected : null;
  const qPerturbed =
    typeof router.query.perturbed === "string" ? router.query.perturbed : null;
  const qTarget =
    typeof router.query.target === "string" ? router.query.target : null;
  const qMode: "general" | "pair" =
    router.query.searchmode === "pair" ? "pair" : "general";
  const qDirection: "target" | "perturbed" =
    router.query.direction === "perturbed" ? "perturbed" : "target";

  useEffect(() => {
    if (!router.isReady) return;
    if (qMode !== searchMode) setSearchMode(qMode);
    if (qDirection !== direction) setDirection(qDirection);

    let cancelled = false;
    const hydrate = async () => {
      if (qMode === "general") {
        if (qSelected) {
          if (selected?.humanSymbol !== qSelected) {
            const s = await resolveSymbol(qSelected);
            if (!cancelled && s) setSelected(s);
          }
        } else if (selected) {
          setSelected(null);
        }
      } else {
        if (qPerturbed) {
          if (perturbed?.humanSymbol !== qPerturbed) {
            const sp = await resolveSymbol(qPerturbed);
            if (!cancelled && sp) setPerturbed(sp);
          }
        } else if (perturbed) {
          setPerturbed(null);
        }
        if (qTarget) {
          if (target?.humanSymbol !== qTarget) {
            const st = await resolveSymbol(qTarget);
            if (!cancelled && st) setTarget(st);
          }
        } else if (target) {
          setTarget(null);
        }
      }
      hydratedFromQuery.current = true;
    };
    hydrate();
    return () => {
      cancelled = true;
    };
  }, [router.isReady, qMode, qSelected, qPerturbed, qTarget, qDirection]);

  // Keep URL in sync with UI state
  useEffect(() => {
    if (!router.isReady) return;
    // Avoid pushing while we're still hydrating initial state
    if (!hydratedFromQuery.current) return;

    const nextQuery: Record<string, string> = { searchmode: searchMode };
    if (searchMode === "general") {
      if (selected?.humanSymbol) nextQuery.selected = selected.humanSymbol;
      // Default 'target' is omitted from the URL to keep it clean.
      if (direction === "perturbed") nextQuery.direction = "perturbed";
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
  }, [searchMode, selected, perturbed, target, direction, router.isReady]);

  useEffect(() => {
    const fetchData = async () => {
      if (!selected) {
        setGeneDescription(null);
        setLlmResult(null);
        return;
      }
      setLoading(true);
      setError(null);
      setGeneralData([]);
      setGeneDescription(null);
      setLlmResult(null);
      try {
        const res = await fetch("/api/gene-data", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            centralGeneId: selected.centralGeneId,
            direction,
          }),
        });
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const payload = await res.json();
        const results = Array.isArray(payload.results) ? payload.results : [];
        setGeneralData(results);
        setGeneDescription(payload.geneDescription ?? null);
        setLlmResult(payload.llmResult ?? null);
      } catch (e: any) {
        setError(e?.message || "Failed to load data");
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [selected, direction]);

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

  const simpleGeneString = (gene: SearchSuggestion | null) => {
    if (!gene) return "Any";
    const mouseStr = gene.mouseSymbols?.join(", ");
    if (mouseStr) {
      return `${gene.humanSymbol} (human) / ${mouseStr} (mouse)`;
    }
    return `${gene.humanSymbol} (human)`;
  };

  const displayGeneString = () => {
    if (searchMode === "general" && selected) {
      return simpleGeneString(selected);
    }
    if (searchMode === "pair" && (perturbed || target)) {
      return `${simpleGeneString(perturbed)} → ${simpleGeneString(target)}`;
    }
    return null;
  };

  const maybeLoading = (
    <>
      {loading && (
        <div
          style={{
            color: "#6b7280",
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
            color: "#dc2626",
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
        <title>SSPsyGene Datasets</title>
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
              color: "#1f2937",
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
          {/* News */}
          <div
            style={{
              width: "min(720px, 92%)",
              boxSizing: "border-box",
              marginBottom: 16,
              background: "#eff6ff",
              border: "1px solid #bfdbfe",
              borderRadius: 8,
              padding: "8px 14px",
              fontSize: 13,
              color: "#1e40af",
            }}
          >
            <span style={{ fontWeight: 600 }}>New</span>{" "}
            <span style={{ color: "#6b7280", fontSize: 12 }}>(Mar 2026)</span>
            {" \u2014 "}
            <a
              href="/most-significant"
              style={{ color: "#2563eb", textDecoration: "none" }}
            >
              Gene ranking by cross-study significance across all datasets now
              available!
            </a>
          </div>
          {/* Mode toggle */}
          <div
            style={{
              width: "min(720px, 92%)",
              boxSizing: "border-box",
              display: "flex",
              gap: 8,
              background: "#f9fafb",
              border: "1px solid #e5e7eb",
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
                  searchMode === "general" ? "#ffffff" : "transparent",
                color: "#1f2937",
                fontWeight: 600,
                boxShadow:
                  searchMode === "general"
                    ? "0 1px 3px rgba(0,0,0,0.1)"
                    : "none",
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
                background: searchMode === "pair" ? "#ffffff" : "transparent",
                color: "#1f2937",
                fontWeight: 600,
                boxShadow:
                  searchMode === "pair" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
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
                background: "#f9fafb",
                border: "1px solid #e5e7eb",
                borderRadius: 12,
                padding: 4,
              }}
            >
              <SearchBar
                placeholder="Search for a gene (e.g., CNTN5, EBF3)"
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
                background: "#f9fafb",
                border: "1px solid #e5e7eb",
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
          {!displayResults() && (
            <div
              style={{
                width: "min(720px, 92%)",
                boxSizing: "border-box",
                marginTop: 24,
                color: "#4b5563",
                fontSize: 15,
                lineHeight: 1.6,
              }}
            >
              <p style={{ margin: 0 }}>
                <strong>The SSPsyGene knowledge base</strong> brings together
                neuropsychiatric-genetics data generated by the{" "}
                <a
                  href="https://sspsygene.org"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "#2563eb", textDecoration: "none" }}
                >
                  SSPsyGene consortium
                </a>{" "}
                — differential-expression studies, perturbation screens (CRISPR
                knockouts, knockdowns, overexpression), and phenotype
                annotations from human, mouse, and zebrafish models of
                psychiatric disease.
              </p>
              <p style={{ marginTop: 12, marginBottom: 0 }}>
                Search for a gene to see every consortium dataset that has
                touched it, with effect sizes and significance shown
                side-by-side across studies. Switch to{" "}
                <strong>Perturbed/Target</strong> mode to look up a specific
                perturbation–readout pair (e.g. &ldquo;what happens to{" "}
                <em>FOXP2</em> when <em>CHD8</em> is knocked out?&rdquo;). Use
                the{" "}
                <a
                  href="/most-significant"
                  style={{ color: "#2563eb", textDecoration: "none" }}
                >
                  cross-study significance ranking
                </a>{" "}
                to see which genes are most consistently implicated across the
                whole consortium. You can also{" "}
                <a
                  href="/full-datasets"
                  style={{ color: "#2563eb", textDecoration: "none" }}
                >
                  view full datasets
                </a>{" "}
                or{" "}
                <a
                  href="/publications"
                  style={{ color: "#2563eb", textDecoration: "none" }}
                >
                  look through the contributing publications
                </a>
                .
              </p>
              <p style={{ marginTop: 12, marginBottom: 0 }}>
                Each dataset&apos;s table shows both nominal p-values from the
                source paper&apos;s analysis and a multiple-testing-corrected
                significance column (typically Benjamini–Hochberg FDR-adjusted)
                — hover any column header to see the exact statistical method
                and correction used. The{" "}
                <a
                  href="/most-significant"
                  style={{ color: "#2563eb", textDecoration: "none" }}
                >
                  cross-study significance ranking
                </a>
                , by contrast, combines <strong>unadjusted</strong> per-study
                p-values, so its combined values can be far smaller than any
                single study&apos;s adjusted p-value (see{" "}
                <a
                  href="/methods"
                  style={{ color: "#2563eb", textDecoration: "none" }}
                >
                  methods
                </a>{" "}
                for details).
              </p>
            </div>
          )}
          <div style={{ width: "100%" }}>
            {displayResults() && (
              <div style={{ width: "100%" }}>
                {maybeLoading}
                {!loading && !error && (
                  <GeneResults
                    geneDisplayName={displayGeneString()}
                    data={searchMode === "general" ? generalData : pairData}
                    assayTypeLabels={assayTypeLabels}
                    centralGeneId={
                      searchMode === "general"
                        ? selected?.centralGeneId
                        : undefined
                    }
                    direction={direction}
                    onDirectionChange={setDirection}
                    perturbedCentralGeneId={
                      searchMode === "pair"
                        ? (perturbed?.centralGeneId ?? null)
                        : undefined
                    }
                    targetCentralGeneId={
                      searchMode === "pair"
                        ? (target?.centralGeneId ?? null)
                        : undefined
                    }
                    geneDescription={
                      searchMode === "general" ? geneDescription : undefined
                    }
                    llmResult={searchMode === "general" ? llmResult : undefined}
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
