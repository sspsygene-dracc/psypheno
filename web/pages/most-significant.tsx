import React, {
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import Head from "next/head";
import Link from "next/link";
import DataTable from "@/components/DataTable";
import DatasetToc, { useAssayGroups } from "@/components/DatasetToc";
import GeneInfoBox from "@/components/GeneInfoBox";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

const PAGE_SIZE = 10;
const NUM_COLS = 6; // rank, gene, pvalue, tables, pvalues, gene info

type RankedRow = {
  rank: number;
  human_symbol: string;
  method_pvalue: number | null;
  num_tables: number;
  num_pvalues: number;
  gene_flags: string | null;
  llm_pubmed_links: string | null;
  llm_summary: string | null;
  llm_search_date: string | null;
  llm_status: string | null;
  gene_description: string | null;
};

type Method = "fisher" | "stouffer" | "cauchy" | "hmp";

const GENE_FLAG_OPTIONS: { key: string; label: string }[] = [
  { key: "heat_shock", label: "Heat shock / chaperones" },
  { key: "mitochondrial_rna", label: "Mitochondrial RNA" },
  { key: "no_hgnc", label: "No HGNC annotation" },
  { key: "non_coding", label: "Non-coding RNA" },
  { key: "pseudogene", label: "Pseudogenes" },
  { key: "ribosomal", label: "Ribosomal proteins" },
  { key: "ubiquitin", label: "Ubiquitin pathway" },
];

type DatasetTableMeta = {
  tableName: string;
  shortLabel: string | null;
  pvalueColumn: string | null;
  fdrColumn: string | null;
  assay: string[] | null;
};

type DatasetSigResult = {
  rows: Record<string, unknown>[];
  totalRows: number;
  displayColumns: string[];
  scalarColumns: string[];
  geneColumns: string[];
  fieldLabels: Record<string, string> | null;
  page: number;
};

const METHOD_DESCRIPTIONS: {
  key: Method;
  label: string;
  shortLabel: string;
  description: string;
  citation?: string;
  doi?: string;
}[] = [
  {
    key: "fisher",
    label: "Fisher\u2019s Method",
    shortLabel: "Fisher",
    description:
      "Combines -2\u00B7\u03A3ln(p) across tables. Pre-collapsed to one p-value per table using a Bonferroni-corrected minimum. Particularly sensitive to any single strong signal. Under H\u2080, the test statistic follows a \u03C7\u00B2 distribution with 2k degrees of freedom (k = number of tables).",
    citation: "Fisher (1925), Statistical Methods for Research Workers",
  },
  {
    key: "stouffer",
    label: "Stouffer\u2019s Method",
    shortLabel: "Stouffer",
    description:
      "Converts p-values to Z-scores via the inverse normal CDF and sums them. Pre-collapsed to one p-value per table. More balanced than Fisher\u2019s method, giving less weight to single extreme values.",
    citation: "Stouffer et al. (1949), The American Soldier",
  },
  {
    key: "cauchy",
    label: "Cauchy Combination Test (CCT)",
    shortLabel: "Cauchy",
    description:
      "Uses all individual p-values directly. Computes a test statistic as a weighted sum of Cauchy-transformed p-values. Robust to arbitrary dependency structures between p-values.",
    citation: "Liu & Xie (2019), JASA",
    doi: "10.1080/01621459.2018.1554485",
  },
  {
    key: "hmp",
    label: "Harmonic Mean P-value (HMP)",
    shortLabel: "HMP",
    description:
      "Computes the weighted harmonic mean of p-values with Landau distribution calibration via R\u2019s harmonicmeanp package. Uses all individual p-values directly. Robust to dependency structure between tests.",
    citation: "Wilson (2019), PNAS",
    doi: "10.1073/pnas.1814092116",
  },
];

function formatPvalue(p: number | null | undefined): string {
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

/* \u2500\u2500\u2500 Pagination component \u2500\u2500\u2500 */
function Pagination({
  page,
  totalPages,
  total,
  loading,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  total: number;
  loading: boolean;
  onPageChange: (p: number) => void;
}) {
  const items: ReactNode[] = [];
  if (totalPages > 1) {
    const addBtn = (label: string | number, target: number, key: string) => {
      const isActive = target === page;
      const isDisabled = loading || target < 1 || target > totalPages;
      items.push(
        <button
          key={key}
          onClick={() => !isDisabled && onPageChange(target)}
          disabled={isDisabled}
          aria-current={isActive ? "page" : undefined}
          style={{
            padding: "6px 10px",
            minWidth: 36,
            background: isActive ? "#f3f4f6" : isDisabled ? "#f9fafb" : "#fff",
            border: "1px solid #d1d5db",
            color: "#1f2937",
            borderRadius: 6,
            cursor: isDisabled ? "not-allowed" : "pointer",
            fontWeight: isActive ? 700 : 500,
          }}
        >
          {label}
        </button>,
      );
    };
    addBtn(1, 1, "pg-1");
    if (totalPages >= 2) addBtn(2, 2, "pg-2");
    const surround: number[] = [];
    for (let p = page - 2; p <= page + 2; p++) {
      if (p >= 1 && p <= totalPages && p !== 1 && p !== 2 && p !== totalPages)
        surround.push(p);
    }
    if (surround.length > 0 && Math.min(...surround) > 3)
      items.push(
        <span key="ell-1" style={{ color: "#6b7280", padding: "0 4px" }}>
          ...
        </span>,
      );
    surround.forEach((pn) => addBtn(pn, pn, `pg-${pn}`));
    if (surround.length > 0 && Math.max(...surround) < totalPages - 1)
      items.push(
        <span key="ell-2" style={{ color: "#6b7280", padding: "0 4px" }}>
          ...
        </span>,
      );
    if (totalPages > 2) addBtn(totalPages, totalPages, "pg-last");
  }

  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 0",
      }}
    >
      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1 || loading}
          style={{
            padding: "8px 12px",
            background: page <= 1 || loading ? "#f9fafb" : "#fff",
            border: "1px solid #d1d5db",
            color: "#1f2937",
            borderRadius: 8,
            cursor: page <= 1 || loading ? "not-allowed" : "pointer",
          }}
        >
          Prev
        </button>
        <button
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages || loading}
          style={{
            padding: "8px 12px",
            background: page >= totalPages || loading ? "#f9fafb" : "#fff",
            border: "1px solid #d1d5db",
            color: "#1f2937",
            borderRadius: 8,
            cursor: page >= totalPages || loading ? "not-allowed" : "pointer",
          }}
        >
          Next
        </button>
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {items}
      </div>
      <div style={{ color: "#6b7280", fontSize: 13, whiteSpace: "nowrap" }}>
        Page {page} of {totalPages} ({total} genes)
      </div>
    </div>
  );
}

/* \u2500\u2500\u2500 Per-dataset significant rows section \u2500\u2500\u2500 */
function DatasetSection({
  meta,
  filterBy,
  sortBy,
}: {
  meta: DatasetTableMeta;
  filterBy: "pvalue" | "fdr";
  sortBy: "pvalue" | "fdr";
}) {
  const [result, setResult] = useState<DatasetSigResult | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setPage(1);
  }, [filterBy, sortBy]);

  useEffect(() => {
    setLoading(true);
    fetch("/api/dataset-significant-rows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tableName: meta.tableName,
        page,
        pageSize: PAGE_SIZE,
        filterBy,
        sortBy,
      }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setResult({
          rows: data.rows,
          totalRows: data.totalRows,
          displayColumns: data.displayColumns,
          scalarColumns: data.scalarColumns,
          geneColumns: data.geneColumns ?? [],
          fieldLabels: data.fieldLabels,
          page: data.page,
        });
        setLoading(false);
      })
      .catch(() => {
        setResult(null);
        setLoading(false);
      });
  }, [meta.tableName, page, filterBy, sortBy]);

  if (!loading && (!result || result.totalRows === 0)) return null;

  const totalPages = result
    ? Math.max(1, Math.ceil(result.totalRows / PAGE_SIZE))
    : 1;

  return (
    <div
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
        <span>{formatTableName(meta.tableName, meta.shortLabel)}</span>
        {result && (
          <span style={{ fontSize: 13, fontWeight: 400, color: "#6b7280" }}>
            {result.totalRows} significant row
            {result.totalRows !== 1 ? "s" : ""}
          </span>
        )}
      </div>
      {loading && (
        <div style={{ padding: 16, color: "#6b7280", fontSize: 14 }}>
          Loading...
        </div>
      )}
      {!loading && result && result.rows.length > 0 && (
        <>
          <DataTable
            columns={result.displayColumns}
            rows={result.rows}
            scalarColumns={result.scalarColumns}
            geneColumns={result.geneColumns}
            fieldLabels={result.fieldLabels ?? undefined}
            showSummary={false}
          />
          {totalPages > 1 && (
            <div
              style={{
                padding: "4px 14px 8px",
                borderTop: "1px solid #e5e7eb",
              }}
            >
              <Pagination
                page={page}
                totalPages={totalPages}
                total={result.totalRows}
                loading={loading}
                onPageChange={setPage}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* \u2500\u2500\u2500 Main page \u2500\u2500\u2500 */
export default function MostSignificantPage() {
  const [rows, setRows] = useState<RankedRow[]>([]);
  const [totalRows, setTotalRows] = useState(0);
  const [page, setPage] = useState(1);
  const [method, setMethod] = useState<Method>("fisher");
  const [loading, setLoading] = useState(true);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const toggleLlmRow = useCallback((symbol: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  }, []);
  const handlePageChange = useCallback((p: number) => {
    setPage(p);
  }, []);

  // Gene flag filter state \u2014 all hidden by default
  const [hideFlags, setHideFlags] = useState<string[]>(
    GENE_FLAG_OPTIONS.map((o) => o.key),
  );

  // Significant rows filter/sort
  const [sigFilterBy, setSigFilterBy] = useState<"pvalue" | "fdr">("pvalue");
  const [sigSortBy, setSigSortBy] = useState<"pvalue" | "fdr">("pvalue");

  // Dataset tables for TOC and significant rows sections
  const [datasetTables, setDatasetTables] = useState<DatasetTableMeta[]>([]);
  const [assayTypeLabels, setAssayTypeLabels] = useState<
    Record<string, string>
  >({});
  const [datasetsLoading, setDatasetsLoading] = useState(true);
  const [showToc, setShowToc] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 900px)");
    setShowToc(mql.matches);
    const handler = (e: MediaQueryListEvent) => setShowToc(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  useEffect(() => {
    fetch("/api/dataset-tables-with-pvalues")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setDatasetTables(data.tables);
        setAssayTypeLabels(data.assayTypeLabels ?? {});
        setDatasetsLoading(false);
      })
      .catch(() => setDatasetsLoading(false));
  }, []);

  const tocGroups = useAssayGroups(datasetTables, assayTypeLabels);

  const selectedMethod =
    METHOD_DESCRIPTIONS.find((m) => m.key === method) ?? METHOD_DESCRIPTIONS[0];

  // Fetch ranked table
  const fetchRanked = useCallback(() => {
    setLoading(true);
    fetch("/api/combined-pvalues-table", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page,
        pageSize: PAGE_SIZE,
        method,
        hideFlags,
      }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setRows(data.rows);
        setTotalRows(data.totalRows);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [page, method, hideFlags]);

  const toggleFlag = (flag: string) => {
    setHideFlags((prev) =>
      prev.includes(flag) ? prev.filter((f) => f !== flag) : [...prev, flag],
    );
    setPage(1);
  };

  useEffect(() => {
    fetchRanked();
  }, [fetchRanked]);

  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));

  return (
    <>
      <Head>
        <title>Most Significant Genes &mdash; SSPsyGene</title>
      </Head>
      <Header />
      {/* Mobile font overrides */}
      <style>{`
        @media (max-width: 700px) {
          .mostsig-gene-info p,
          .mostsig-gene-info div,
          .mostsig-gene-info span {
            font-size: 13px !important;
            line-height: 1.5 !important;
            -webkit-text-size-adjust: 100% !important;
          }
          .mostsig-method-desc {
            font-size: 12px !important;
            line-height: 1.5 !important;
          }
        }
      `}</style>
      <main
        style={{
          maxWidth: showToc ? 1200 : 1000,
          margin: "0 auto",
          padding: "24px 16px",
          color: "#1f2937",
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>
          Ranking the Most Significant Genes Across All Datasets
        </h1>
        <p
          style={{
            color: "#4b5563",
            fontSize: 15,
            lineHeight: 1.7,
            marginBottom: 20,
          }}
        >
          This page ranks genes by their aggregate statistical significance
          across all datasets in SSPsyGene. It identifies genes with the
          strongest cumulative evidence of association across multiple
          independent experiments, highlighting candidates for follow-up
          analysis, cross-study validation, or pathway enrichment. Use the
          method selector below to compare how rankings change depending on the
          statistical combination approach.
        </p>

        {/* Method selector */}
        <div
          style={{
            marginBottom: 12,
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <label
            htmlFor="method-select"
            style={{ fontWeight: 600, fontSize: 14, color: "#374151" }}
          >
            Ranking method:
          </label>
          <select
            id="method-select"
            value={method}
            onChange={(e) => {
              setMethod(e.target.value as Method);
              setPage(1);
            }}
            style={{
              padding: "6px 12px",
              borderRadius: 6,
              border: "1px solid #d1d5db",
              fontSize: 14,
            }}
          >
            {METHOD_DESCRIPTIONS.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </div>

        {/* Selected method description */}
        <div
          className="mostsig-method-desc"
          style={{
            marginBottom: 16,
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            padding: "10px 14px",
            fontSize: 13,
            color: "#6b7280",
          }}
        >
          <strong style={{ color: "#374151" }}>{selectedMethod.label}:</strong>{" "}
          {selectedMethod.description}
          {selectedMethod.citation && (
            <span style={{ fontStyle: "italic" }}>
              {" \u2014 "}
              {selectedMethod.doi ? (
                <a
                  href={`https://doi.org/${selectedMethod.doi}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "#2563eb", textDecoration: "none" }}
                >
                  {selectedMethod.citation}
                </a>
              ) : (
                selectedMethod.citation
              )}
            </span>
          )}
          <div style={{ marginTop: 6 }}>
            <Link
              href="/methods"
              style={{
                color: "#2563eb",
                textDecoration: "none",
                fontSize: 13,
              }}
            >
              Full methods documentation &rarr;
            </Link>
          </div>
        </div>

        {/* Gene category filter */}
        <div
          id="gene-filters"
          style={{
            marginBottom: 16,
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            padding: "10px 14px",
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
            fontSize: 13,
          }}
        >
          <span
            style={{ fontWeight: 600, color: "#374151", whiteSpace: "nowrap" }}
          >
            Hide gene categories:
          </span>
          {GENE_FLAG_OPTIONS.map((opt) => (
            <label
              key={opt.key}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 4,
                cursor: "pointer",
                color: "#4b5563",
                whiteSpace: "nowrap",
              }}
            >
              <input
                type="checkbox"
                checked={hideFlags.includes(opt.key)}
                onChange={() => toggleFlag(opt.key)}
              />
              {opt.label}
            </label>
          ))}
          {hideFlags.length > 0 && (
            <button
              onClick={() => {
                setHideFlags([]);
                setPage(1);
              }}
              style={{
                padding: "2px 8px",
                fontSize: 12,
                background: "#fff",
                border: "1px solid #d1d5db",
                borderRadius: 4,
                cursor: "pointer",
                color: "#6b7280",
              }}
            >
              Show all
            </button>
          )}
          {hideFlags.length < GENE_FLAG_OPTIONS.length && (
            <button
              onClick={() => {
                setHideFlags(GENE_FLAG_OPTIONS.map((o) => o.key));
                setPage(1);
              }}
              style={{
                padding: "2px 8px",
                fontSize: 12,
                background: "#fff",
                border: "1px solid #d1d5db",
                borderRadius: 4,
                cursor: "pointer",
                color: "#6b7280",
              }}
            >
              Hide all
            </button>
          )}
        </div>

        {/* Ranked genes table */}
        <div
          id="ranked-genes-table"
          style={{
            background: "#ffffff",
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            overflow: "hidden",
            marginBottom: 24,
          }}
        >
          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 14,
                WebkitTextSizeAdjust: "100%",
              }}
            >
              <thead>
                <tr style={{ background: "#f9fafb" }}>
                  <th
                    style={{
                      padding: "10px 12px",
                      textAlign: "right",
                      fontWeight: 600,
                      color: "#6b7280",
                      whiteSpace: "nowrap",
                      borderBottom: "1px solid #e5e7eb",
                    }}
                  >
                    {selectedMethod.shortLabel} rank
                  </th>
                  <th
                    style={{
                      padding: "10px 12px",
                      textAlign: "left",
                      fontWeight: 600,
                      color: "#6b7280",
                      whiteSpace: "nowrap",
                      borderBottom: "1px solid #e5e7eb",
                    }}
                  >
                    Gene
                  </th>
                  <th
                    style={{
                      padding: "10px 12px",
                      textAlign: "left",
                      fontWeight: 600,
                      color: "#6b7280",
                      whiteSpace: "nowrap",
                      borderBottom: "1px solid #e5e7eb",
                    }}
                  >
                    {selectedMethod.shortLabel} p-value
                  </th>
                  <th
                    style={{
                      padding: "10px 12px",
                      textAlign: "right",
                      fontWeight: 600,
                      color: "#6b7280",
                      whiteSpace: "nowrap",
                      borderBottom: "1px solid #e5e7eb",
                    }}
                  >
                    Tables
                  </th>
                  <th
                    style={{
                      padding: "10px 12px",
                      textAlign: "right",
                      fontWeight: 600,
                      color: "#6b7280",
                      whiteSpace: "nowrap",
                      borderBottom: "1px solid #e5e7eb",
                    }}
                  >
                    P-values
                  </th>
                  <th
                    style={{
                      padding: "10px 12px",
                      fontWeight: 600,
                      color: "#6b7280",
                      whiteSpace: "nowrap",
                      borderBottom: "1px solid #e5e7eb",
                      textAlign: "center",
                    }}
                  >
                    Gene Info
                  </th>
                </tr>
              </thead>
              <tbody key={`page-${page}-${method}`}>
                {rows.length === 0 && loading && (
                  <tr>
                    <td
                      colSpan={NUM_COLS}
                      style={{
                        padding: 24,
                        textAlign: "center",
                        color: "#6b7280",
                      }}
                    >
                      Loading...
                    </td>
                  </tr>
                )}
                {rows.map((row, idx) => {
                  const isExpanded = expandedRows.has(row.human_symbol);

                  return (
                    <React.Fragment key={`${row.human_symbol}-${idx}`}>
                      <tr style={{ borderTop: "1px solid #e5e7eb" }}>
                        {/* Rank */}
                        <td
                          style={{
                            padding: "8px 12px",
                            textAlign: "right",
                            whiteSpace: "nowrap",
                            color: "#6b7280",
                          }}
                        >
                          {row.rank}
                        </td>
                        {/* Gene */}
                        <td
                          style={{
                            padding: "8px 12px",
                            whiteSpace: "nowrap",
                          }}
                        >
                          <Link
                            href={`/?searchMode=general&selected=${encodeURIComponent(row.human_symbol)}`}
                            style={{
                              color: "#2563eb",
                              textDecoration: "none",
                              fontWeight: 500,
                            }}
                          >
                            {row.human_symbol}
                          </Link>
                        </td>
                        {/* P-value */}
                        <td
                          style={{
                            padding: "8px 12px",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {formatPvalue(row.method_pvalue)}
                        </td>
                        {/* Tables */}
                        <td
                          style={{
                            padding: "8px 12px",
                            textAlign: "right",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {row.num_tables}
                        </td>
                        {/* P-values count */}
                        <td
                          style={{
                            padding: "8px 12px",
                            textAlign: "right",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {row.num_pvalues}
                        </td>
                        {/* Gene Info toggle */}
                        <td
                          style={{
                            padding: "8px 12px",
                            textAlign: "center",
                          }}
                        >
                          <button
                            onClick={() => toggleLlmRow(row.human_symbol)}
                            title={
                              isExpanded ? "Hide gene info" : "Show gene info"
                            }
                            style={{
                              padding: "2px 8px",
                              fontSize: 12,
                              background: isExpanded ? "#e5e7eb" : "#fff",
                              border: "1px solid #d1d5db",
                              borderRadius: 4,
                              cursor: "pointer",
                              color: "#4b5563",
                            }}
                          >
                            {isExpanded ? "\u25B4 Hide" : "\u25BE Show"}
                          </button>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr
                          style={{
                            background: "#f9fafb",
                            borderTop: "1px solid #e5e7eb",
                          }}
                        >
                          <td
                            colSpan={NUM_COLS}
                            className="mostsig-gene-info"
                            style={{ padding: "10px 14px" }}
                          >
                            <GeneInfoBox
                              geneDescription={row.gene_description}
                              llmResult={{
                                summary: row.llm_summary,
                                pubmedLinks: row.llm_pubmed_links,
                                status: row.llm_status ?? "not_searched",
                                searchDate: row.llm_search_date,
                              }}
                            />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div
              style={{
                padding: "4px 14px 8px",
                borderTop: "1px solid #e5e7eb",
              }}
            >
              <Pagination
                page={page}
                totalPages={totalPages}
                total={totalRows}
                loading={loading}
                onPageChange={handlePageChange}
              />
            </div>
          )}
        </div>

        {/* Significant rows per dataset */}
        <div
          id="significant-rows"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            marginBottom: 12,
            flexWrap: "wrap",
          }}
        >
          <h2 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>
            Significant Rows (&lt; 0.05) by Dataset
          </h2>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 13,
            }}
          >
            <span style={{ color: "#6b7280" }}>Rows where</span>
            <select
              value={sigFilterBy}
              onChange={(e) =>
                setSigFilterBy(e.target.value as "pvalue" | "fdr")
              }
              style={{
                padding: "4px 8px",
                borderRadius: 6,
                border: "1px solid #d1d5db",
                fontSize: 13,
              }}
            >
              <option value="pvalue">p-value</option>
              <option value="fdr">FDR</option>
            </select>
            <span style={{ color: "#6b7280" }}>&lt; 0.05, sorted by</span>
            <select
              value={sigSortBy}
              onChange={(e) => setSigSortBy(e.target.value as "pvalue" | "fdr")}
              style={{
                padding: "4px 8px",
                borderRadius: 6,
                border: "1px solid #d1d5db",
                fontSize: 13,
              }}
            >
              <option value="pvalue">p-value</option>
              <option value="fdr">FDR</option>
            </select>
          </div>
        </div>

        <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
          {showToc && tocGroups.length > 0 && (
            <DatasetToc groups={tocGroups} anchorPrefix="sig-dataset-" />
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            {datasetsLoading ? (
              <div style={{ color: "#6b7280", padding: "12px 0" }}>
                Loading datasets...
              </div>
            ) : (
              tocGroups.map((group) => {
                const items = group.items as DatasetTableMeta[];
                const filtered = items.filter((t) =>
                  sigFilterBy === "pvalue" ? t.pvalueColumn : t.fdrColumn,
                );
                if (filtered.length === 0) return null;
                return (
                  <div key={group.assayKey}>
                    {tocGroups.length > 1 && (
                      <div
                        style={{
                          marginTop: 24,
                          marginBottom: 6,
                          padding: "8px 0",
                          borderBottom: "2px solid #dbeafe",
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                        }}
                      >
                        <span
                          style={{
                            fontSize: 13,
                            fontWeight: 600,
                            color: "#1e40af",
                            backgroundColor: "#dbeafe",
                            borderRadius: 9999,
                            padding: "3px 10px",
                            textTransform: "uppercase",
                            letterSpacing: "0.03em",
                          }}
                        >
                          {group.label}
                        </span>
                        <span style={{ fontSize: 13, color: "#6b7280" }}>
                          {filtered.length} dataset
                          {filtered.length !== 1 ? "s" : ""}
                        </span>
                      </div>
                    )}
                    {filtered.map((t) => (
                      <div
                        key={t.tableName}
                        id={`sig-dataset-${t.tableName}`}
                        style={{ scrollMarginTop: 16 }}
                      >
                        <DatasetSection
                          meta={t}
                          filterBy={sigFilterBy}
                          sortBy={sigSortBy}
                        />
                      </div>
                    ))}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}
