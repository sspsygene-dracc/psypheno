import { useEffect, useState, useRef } from "react";
import Head from "next/head";
import { useRouter } from "next/router";
import SearchBar from "@/components/SearchBar";
import GeneResults from "@/components/GeneResults";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import InfoTooltip from "@/components/InfoTooltip";
import { TableResult } from "@/lib/table_result";
import { SearchSuggestion } from "@/state/SearchSuggestion";

export default function Home() {
  const router = useRouter();
  const [perturbed, setPerturbed] = useState<SearchSuggestion | null>(null);
  const [target, setTarget] = useState<SearchSuggestion | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [pairData, setPairData] = useState<TableResult[]>([]);
  const [assayTypeLabels, setAssayTypeLabels] = useState<
    Record<string, string>
  >({});
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

  const qPerturbed =
    typeof router.query.perturbed === "string" ? router.query.perturbed : null;
  const qTarget =
    typeof router.query.target === "string" ? router.query.target : null;

  useEffect(() => {
    if (!router.isReady) return;

    let cancelled = false;
    const hydrate = async () => {
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
      hydratedFromQuery.current = true;
    };
    hydrate();
    return () => {
      cancelled = true;
    };
  }, [router.isReady, qPerturbed, qTarget]);

  // Keep URL in sync with UI state
  useEffect(() => {
    if (!router.isReady) return;
    if (!hydratedFromQuery.current) return;

    const nextQuery: Record<string, string> = {};
    if (perturbed?.humanSymbol) nextQuery.perturbed = perturbed.humanSymbol;
    if (target?.humanSymbol) nextQuery.target = target.humanSymbol;

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
  }, [perturbed, target, router.isReady]);

  useEffect(() => {
    const fetchPair = async () => {
      if (!perturbed && !target) {
        setPairData([]);
        return;
      }
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

  const showResults = perturbed != null || target != null;

  const simpleGeneString = (gene: SearchSuggestion | null) => {
    if (!gene) return "Any";
    const mouseStr = gene.mouseSymbols?.join(", ");
    if (mouseStr) {
      return `${gene.humanSymbol} (human) / ${mouseStr} (mouse)`;
    }
    return `${gene.humanSymbol} (human)`;
  };

  const displayGeneString = () => {
    if (!showResults) return null;
    return `${simpleGeneString(perturbed)} → ${simpleGeneString(target)}`;
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
            {" — "}
            <a
              href="/most-significant"
              style={{ color: "#2563eb", textDecoration: "none" }}
            >
              Gene ranking by cross-study significance across all datasets now
              available!
            </a>
          </div>

          <div
            style={{
              width: "min(720px, 92%)",
              boxSizing: "border-box",
              marginTop: 16,
              background: "#f9fafb",
              border: "1px solid #e5e7eb",
              borderRadius: 12,
              padding: 8,
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 12,
            }}
          >
            <div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  fontSize: 13,
                  fontWeight: 600,
                  color: "#374151",
                  padding: "4px 6px 6px",
                }}
              >
                <span>Perturbed gene</span>
                <InfoTooltip
                  size={13}
                  text="The gene that was experimentally manipulated in this dataset's experiment — knocked down (CRISPRi, RNAi/shRNA), upregulated (CRISPRa, overexpression), knocked out (CRISPR-KO), or carried as a mutant allele. Leave blank to skip the perturbation filter."
                />
              </div>
              <SearchBar
                placeholder="Perturbed gene"
                onSelect={(s) => setPerturbed(s)}
                value={perturbed}
              />
            </div>
            <div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  fontSize: 13,
                  fontWeight: 600,
                  color: "#374151",
                  padding: "4px 6px 6px",
                }}
              >
                <span>Target gene</span>
                <InfoTooltip
                  size={13}
                  text="The gene whose expression or activity was measured as a readout — i.e. how the genome responded. Leave blank to skip the readout filter."
                />
              </div>
              <SearchBar
                placeholder="Target gene"
                onSelect={(s) => setTarget(s)}
                value={target}
              />
            </div>
          </div>

          {!showResults && (
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
                Search for a gene as <strong>perturbed</strong> (the gene that
                was experimentally manipulated — CRISPRi/CRISPRa, RNAi,
                knockout, mutant line) or as <strong>target</strong> (the
                readout whose expression or activity was measured), or fill in
                both fields to find consortium data on a specific
                perturbation→readout pair — e.g. &ldquo;what happens to{" "}
                <em>CNR1</em> when <em>FOXG1</em> is knocked down?&rdquo;. Use
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
            {showResults && (
              <div style={{ width: "100%" }}>
                {maybeLoading}
                {!loading && !error && (
                  <GeneResults
                    geneDisplayName={displayGeneString()}
                    data={pairData}
                    assayTypeLabels={assayTypeLabels}
                    perturbedGene={perturbed}
                    targetGene={target}
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
