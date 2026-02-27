import { useEffect, useState, useRef } from "react";
import Head from "next/head";
import { useRouter } from "next/router";
import SearchBar from "@/components/SearchBar";
import DataTable from "@/components/DataTable";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { SearchSuggestion } from "@/state/SearchSuggestion";

type CombinedPvalues = {
  fisher: number | null;
  stouffer: number | null;
  cauchy: number | null;
  hmp: number | null;
  numTables: number;
  numPvalues: number;
};

type ContributingTable = {
  tableName: string;
  shortLabel: string | null;
  description: string | null;
  pvalueColumn: string | null;
  fdrColumn: string | null;
  rowCount: number;
};

type SignificantTable = {
  tableName: string;
  shortLabel: string | null;
  pvalueColumn: string | null;
  fdrColumn: string | null;
  fieldLabels: Record<string, string> | null;
  displayColumns: string[];
  scalarColumns: string[];
  rows: Record<string, unknown>[];
  totalSignificantRows: number;
};

const METHOD_DESCRIPTIONS: Record<string, string> = {
  fisher:
    "Combines -2\u00B7\u03A3ln(p) across tables. P-values are pre-collapsed to one per table using Bonferroni-corrected minimum. Sensitive to any single strong signal.",
  stouffer:
    "Converts p-values to Z-scores and sums them. Pre-collapsed to one per table. More balanced than Fisher\u2019s \u2014 doesn\u2019t let one extreme p-value dominate.",
  cauchy:
    "Cauchy combination test (CCT). Uses tan-transform of all individual p-values directly (no pre-collapsing). Robust to correlated p-values from the same dataset.",
  hmp: "Harmonic mean p-value. Weighted harmonic mean of all individual p-values directly (no pre-collapsing). Robust to dependency structure between tests.",
};

function formatPvalue(p: number | null): string {
  if (p === null || p === undefined) return "\u2014";
  if (p < 1e-300) return "< 1e-300";
  if (p < 0.001) return p.toExponential(3);
  return p.toPrecision(4);
}

const formatTableName = (tableName: string, shortLabel: string | null) =>
  shortLabel ??
  tableName
    .replace(/_/g, " ")
    .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1));

export default function CombinedPvaluesPage() {
  const router = useRouter();
  const [selected, setSelected] = useState<SearchSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [combinedPvalues, setCombinedPvalues] =
    useState<CombinedPvalues | null>(null);
  const [contributingTables, setContributingTables] = useState<
    ContributingTable[]
  >([]);
  const [significantTables, setSignificantTables] = useState<
    SignificantTable[]
  >([]);
  const [filterBy, setFilterBy] = useState<"pvalue" | "fdr">("pvalue");
  const [sortBy, setSortBy] = useState<"pvalue" | "fdr">("pvalue");
  const [sigLoading, setSigLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const hydratedFromQuery = useRef(false);

  // Resolve gene symbol from URL
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
      };
      const suggestions = Array.isArray(data.suggestions)
        ? data.suggestions
        : [];
      const exact = suggestions.find((s) => s.humanSymbol === symbol);
      return exact || suggestions[0] || null;
    } catch {
      return null;
    }
  };

  // Hydrate from URL
  useEffect(() => {
    if (!router.isReady || hydratedFromQuery.current) return;
    const q = router.query || {};
    const sel = typeof q.selected === "string" ? q.selected : undefined;
    if (sel) {
      (async () => {
        const s = await resolveSymbol(sel);
        if (s) setSelected(s);
      })();
    }
    hydratedFromQuery.current = true;
  }, [router.isReady, router.query]);

  // Sync URL
  useEffect(() => {
    if (!hydratedFromQuery.current) return;
    const params: Record<string, string> = {};
    if (selected?.humanSymbol) params.selected = selected.humanSymbol;
    const qs = new URLSearchParams(params).toString();
    const target = qs ? `?${qs}` : router.pathname;
    if (target !== `${router.pathname}${window.location.search}`) {
      router.replace(target, undefined, { shallow: true });
    }
  }, [selected]);

  // Fetch combined p-values when gene changes
  useEffect(() => {
    if (!selected) {
      setCombinedPvalues(null);
      setContributingTables([]);
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);

    fetch("/api/combined-pvalues", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ centralGeneId: selected.centralGeneId }),
      signal: controller.signal,
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setCombinedPvalues(data.combinedPvalues);
        setContributingTables(data.contributingTables);
        setLoading(false);
      })
      .catch((e) => {
        if (e.name === "AbortError") return;
        setError(e.message || "Failed to load");
        setLoading(false);
      });
  }, [selected]);

  // Fetch significant rows when gene or filter/sort changes
  useEffect(() => {
    if (!selected) {
      setSignificantTables([]);
      return;
    }
    setSigLoading(true);

    fetch("/api/significant-rows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        centralGeneId: selected.centralGeneId,
        filterBy,
        sortBy,
      }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setSignificantTables(data.tables);
        setSigLoading(false);
      })
      .catch((e) => {
        if (e.name === "AbortError") return;
        setSigLoading(false);
      });
  }, [selected, filterBy, sortBy]);

  const geneDisplay = selected?.humanSymbol || null;

  return (
    <>
      <Head>
        <title>
          {geneDisplay
            ? `${geneDisplay} Combined P-values — SSPsyGene`
            : "Combined P-values — SSPsyGene"}
        </title>
      </Head>
      <Header />
      <main
        style={{
          maxWidth: 1100,
          margin: "0 auto",
          padding: "24px 16px",
          color: "#1f2937",
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>
          Combined P-values
        </h1>
        <p
          style={{
            color: "#6b7280",
            fontSize: 14,
            marginBottom: 20,
            maxWidth: 800,
          }}
        >
          Aggregate statistical significance across all datasets for a gene.
          Combines p-values using four complementary methods: Fisher and Stouffer
          (pre-collapsed to one p-value per dataset), and Cauchy/HMP (using all
          individual p-values, robust to correlation).
        </p>

        <div style={{ maxWidth: 500, marginBottom: 24 }}>
          <SearchBar
            placeholder="Search for a gene..."
            onSelect={(s) => setSelected(s)}
            value={selected}
          />
        </div>

        {loading && (
          <div style={{ color: "#6b7280", padding: "20px 0" }}>
            Loading combined p-values...
          </div>
        )}
        {error && (
          <div style={{ color: "#dc2626", padding: "20px 0" }}>{error}</div>
        )}

        {!loading && geneDisplay && combinedPvalues && (
          <>
            <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 12 }}>
              Results for {geneDisplay}
            </h2>

            {/* Combined p-values card */}
            <div
              style={{
                background: "#ffffff",
                border: "1px solid #e5e7eb",
                borderRadius: 12,
                overflow: "hidden",
                marginBottom: 20,
              }}
            >
              <div
                style={{
                  padding: "12px 14px",
                  borderBottom: "1px solid #e5e7eb",
                  fontWeight: 600,
                }}
              >
                Combined P-values
                <span
                  style={{
                    fontWeight: 400,
                    color: "#6b7280",
                    fontSize: 13,
                    marginLeft: 12,
                  }}
                >
                  {combinedPvalues.numPvalues} p-values from{" "}
                  {combinedPvalues.numTables} table
                  {combinedPvalues.numTables !== 1 ? "s" : ""}
                </span>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: 14,
                  }}
                >
                  <thead>
                    <tr style={{ borderBottom: "1px solid #e5e7eb" }}>
                      <th
                        style={{
                          textAlign: "left",
                          padding: "10px 14px",
                          fontWeight: 600,
                          color: "#374151",
                        }}
                      >
                        Method
                      </th>
                      <th
                        style={{
                          textAlign: "left",
                          padding: "10px 14px",
                          fontWeight: 600,
                          color: "#374151",
                          whiteSpace: "nowrap",
                        }}
                      >
                        Combined p-value
                      </th>
                      <th
                        style={{
                          textAlign: "left",
                          padding: "10px 14px",
                          fontWeight: 600,
                          color: "#374151",
                        }}
                      >
                        Description
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(
                      [
                        ["Fisher\u2019s method", combinedPvalues.fisher, "fisher"],
                        ["Stouffer\u2019s method", combinedPvalues.stouffer, "stouffer"],
                        ["Cauchy (CCT)", combinedPvalues.cauchy, "cauchy"],
                        ["Harmonic Mean (HMP)", combinedPvalues.hmp, "hmp"],
                      ] as [string, number | null, string][]
                    ).map(([name, value, key]) => (
                      <tr
                        key={key}
                        style={{ borderBottom: "1px solid #f3f4f6" }}
                      >
                        <td
                          style={{
                            padding: "10px 14px",
                            fontWeight: 500,
                            whiteSpace: "nowrap",
                          }}
                        >
                          {name}
                        </td>
                        <td
                          style={{
                            padding: "10px 14px",
                            fontFamily: "monospace",
                            color:
                              value !== null && value < 0.05
                                ? "#059669"
                                : "#1f2937",
                            fontWeight:
                              value !== null && value < 0.05 ? 600 : 400,
                          }}
                        >
                          {formatPvalue(value)}
                        </td>
                        <td
                          style={{
                            padding: "10px 14px",
                            color: "#6b7280",
                            fontSize: 13,
                          }}
                        >
                          {METHOD_DESCRIPTIONS[key]}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Contributing tables */}
            {contributingTables.length > 0 && (
              <div
                style={{
                  background: "#ffffff",
                  border: "1px solid #e5e7eb",
                  borderRadius: 12,
                  overflow: "hidden",
                  marginBottom: 24,
                }}
              >
                <div
                  style={{
                    padding: "12px 14px",
                    borderBottom: "1px solid #e5e7eb",
                    fontWeight: 600,
                  }}
                >
                  Contributing Datasets
                </div>
                <div style={{ overflowX: "auto" }}>
                  <table
                    style={{
                      width: "100%",
                      borderCollapse: "collapse",
                      fontSize: 14,
                    }}
                  >
                    <thead>
                      <tr style={{ borderBottom: "1px solid #e5e7eb" }}>
                        <th
                          style={{
                            textAlign: "left",
                            padding: "10px 14px",
                            fontWeight: 600,
                            color: "#374151",
                          }}
                        >
                          Dataset
                        </th>
                        <th
                          style={{
                            textAlign: "left",
                            padding: "10px 14px",
                            fontWeight: 600,
                            color: "#374151",
                          }}
                        >
                          P-value column
                        </th>
                        <th
                          style={{
                            textAlign: "left",
                            padding: "10px 14px",
                            fontWeight: 600,
                            color: "#374151",
                          }}
                        >
                          FDR column
                        </th>
                        <th
                          style={{
                            textAlign: "right",
                            padding: "10px 14px",
                            fontWeight: 600,
                            color: "#374151",
                          }}
                        >
                          Rows for gene
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {contributingTables.map((t) => (
                        <tr
                          key={t.tableName}
                          style={{ borderBottom: "1px solid #f3f4f6" }}
                        >
                          <td style={{ padding: "10px 14px" }}>
                            <div style={{ fontWeight: 500 }}>
                              {formatTableName(t.tableName, t.shortLabel)}
                            </div>
                            {t.description && (
                              <div
                                style={{
                                  fontSize: 12,
                                  color: "#6b7280",
                                  marginTop: 2,
                                }}
                              >
                                {t.description.length > 120
                                  ? t.description.slice(0, 120) + "..."
                                  : t.description}
                              </div>
                            )}
                          </td>
                          <td
                            style={{
                              padding: "10px 14px",
                              fontFamily: "monospace",
                              fontSize: 13,
                            }}
                          >
                            {t.pvalueColumn || "\u2014"}
                          </td>
                          <td
                            style={{
                              padding: "10px 14px",
                              fontFamily: "monospace",
                              fontSize: 13,
                            }}
                          >
                            {t.fdrColumn || "\u2014"}
                          </td>
                          <td
                            style={{
                              padding: "10px 14px",
                              textAlign: "right",
                            }}
                          >
                            {t.rowCount}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Significant rows section */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 16,
                marginBottom: 12,
                flexWrap: "wrap",
              }}
            >
              <h2
                style={{ fontSize: 20, fontWeight: 600, margin: 0 }}
              >
                Significant Rows (&lt; 0.05)
              </h2>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 13,
                }}
              >
                <span style={{ color: "#6b7280" }}>Filter by:</span>
                <select
                  value={filterBy}
                  onChange={(e) =>
                    setFilterBy(e.target.value as "pvalue" | "fdr")
                  }
                  style={{
                    padding: "4px 8px",
                    borderRadius: 6,
                    border: "1px solid #d1d5db",
                    fontSize: 13,
                  }}
                >
                  <option value="pvalue">P-value</option>
                  <option value="fdr">FDR</option>
                </select>
                <span style={{ color: "#6b7280", marginLeft: 8 }}>
                  Sort by:
                </span>
                <select
                  value={sortBy}
                  onChange={(e) =>
                    setSortBy(e.target.value as "pvalue" | "fdr")
                  }
                  style={{
                    padding: "4px 8px",
                    borderRadius: 6,
                    border: "1px solid #d1d5db",
                    fontSize: 13,
                  }}
                >
                  <option value="pvalue">P-value ascending</option>
                  <option value="fdr">FDR ascending</option>
                </select>
              </div>
            </div>

            {sigLoading && (
              <div style={{ color: "#6b7280", padding: "12px 0" }}>
                Loading significant rows...
              </div>
            )}

            {!sigLoading && significantTables.length === 0 && (
              <div style={{ color: "#6b7280", padding: "12px 0" }}>
                No rows below 0.05 threshold found for {geneDisplay} with the
                selected filter.
              </div>
            )}

            {!sigLoading &&
              significantTables.map((t) => (
                <div
                  key={t.tableName}
                  style={{
                    marginBottom: 16,
                    background: "#ffffff",
                    border: "1px solid #e5e7eb",
                    borderRadius: 12,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      padding: "12px 14px",
                      borderBottom: "1px solid #e5e7eb",
                      fontWeight: 600,
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <span>
                      {formatTableName(t.tableName, t.shortLabel)}
                    </span>
                    <span
                      style={{
                        fontSize: 13,
                        fontWeight: 400,
                        color: "#6b7280",
                      }}
                    >
                      {t.totalSignificantRows} significant row
                      {t.totalSignificantRows !== 1 ? "s" : ""}
                    </span>
                  </div>
                  <DataTable
                    columns={t.displayColumns}
                    rows={t.rows}
                    scalarColumns={t.scalarColumns}
                    fieldLabels={t.fieldLabels ?? undefined}
                  />
                  {t.totalSignificantRows > t.rows.length && (
                    <div
                      style={{
                        padding: "8px 14px",
                        fontSize: 13,
                        color: "#6b7280",
                        borderTop: "1px solid #e5e7eb",
                        background: "#f9fafb",
                      }}
                    >
                      Showing {t.rows.length} of {t.totalSignificantRows}{" "}
                      significant rows
                    </div>
                  )}
                </div>
              ))}
          </>
        )}

        {!loading && geneDisplay && !combinedPvalues && (
          <div style={{ color: "#6b7280", padding: "20px 0" }}>
            No p-value data available for {geneDisplay} across any dataset.
          </div>
        )}
      </main>
      <Footer />
    </>
  );
}
