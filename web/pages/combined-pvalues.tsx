import { useEffect, useState, useCallback, type ReactNode } from "react";
import Head from "next/head";
import Link from "next/link";
import DataTable from "@/components/DataTable";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

const PAGE_SIZE = 10;

type CombinedRow = {
  human_symbol: string;
  fisher_pvalue: number | null;
  fisher_fdr: number | null;
  stouffer_pvalue: number | null;
  stouffer_fdr: number | null;
  cauchy_pvalue: number | null;
  cauchy_fdr: number | null;
  hmp_pvalue: number | null;
  hmp_fdr: number | null;
  num_tables: number;
  num_pvalues: number;
  gene_flags: string | null;
};

const GENE_FLAG_OPTIONS: { key: string; label: string }[] = [
  { key: "heat_shock", label: "Heat shock / chaperones" },
  { key: "ribosomal", label: "Ribosomal proteins" },
  { key: "ubiquitin", label: "Ubiquitin pathway" },
  { key: "non_coding", label: "Non-coding RNA" },
  { key: "mitochondrial_rna", label: "Mitochondrial RNA" },
];

type DatasetTableMeta = {
  tableName: string;
  shortLabel: string | null;
  pvalueColumn: string | null;
  fdrColumn: string | null;
};

type DatasetSigResult = {
  rows: Record<string, unknown>[];
  totalRows: number;
  displayColumns: string[];
  scalarColumns: string[];
  fieldLabels: Record<string, string> | null;
  page: number;
};

const METHOD_DESCRIPTIONS: Record<string, string> = {
  fisher:
    "Combines -2\u00B7\u03A3ln(p) across tables. Pre-collapsed to one p-value per table (Bonferroni-corrected minimum). Sensitive to any single strong signal.",
  stouffer:
    "Converts p-values to Z-scores and sums. Pre-collapsed to one per table. More balanced than Fisher\u2019s.",
  cauchy:
    "Cauchy combination test (CCT). Uses all individual p-values directly. Robust to correlated p-values.",
  hmp: "Harmonic mean p-value. Uses all individual p-values directly. Robust to dependency structure.",
};

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

type SortColumn =
  | "human_symbol"
  | "fisher_pvalue"
  | "fisher_fdr"
  | "stouffer_pvalue"
  | "stouffer_fdr"
  | "cauchy_pvalue"
  | "cauchy_fdr"
  | "hmp_pvalue"
  | "hmp_fdr"
  | "num_tables"
  | "num_pvalues";

const COMBINED_COLUMNS: {
  key: SortColumn;
  label: string;
  mono?: boolean;
  right?: boolean;
}[] = [
  { key: "human_symbol", label: "Gene" },
  { key: "fisher_pvalue", label: "Fisher p", mono: true },
  { key: "fisher_fdr", label: "Fisher FDR", mono: true },
  { key: "stouffer_pvalue", label: "Stouffer p", mono: true },
  { key: "stouffer_fdr", label: "Stouffer FDR", mono: true },
  { key: "cauchy_pvalue", label: "Cauchy p", mono: true },
  { key: "cauchy_fdr", label: "Cauchy FDR", mono: true },
  { key: "hmp_pvalue", label: "HMP p", mono: true },
  { key: "hmp_fdr", label: "HMP FDR", mono: true },
  { key: "num_tables", label: "Tables", right: true },
  { key: "num_pvalues", label: "P-values", right: true },
];

/* ─── Pagination component ─── */
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
        </button>
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
        </span>
      );
    surround.forEach((pn) => addBtn(pn, pn, `pg-${pn}`));
    if (surround.length > 0 && Math.max(...surround) < totalPages - 1)
      items.push(
        <span key="ell-2" style={{ color: "#6b7280", padding: "0 4px" }}>
          ...
        </span>
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
            cursor:
              page >= totalPages || loading ? "not-allowed" : "pointer",
          }}
        >
          Next
        </button>
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {items}
      </div>
      <div style={{ color: "#6b7280", fontSize: 13, whiteSpace: "nowrap" }}>
        Page {page} of {totalPages} ({total} rows)
      </div>
    </div>
  );
}

/* ─── Per-dataset significant rows section ─── */
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

  // Reset page when filter/sort changes
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
          <span
            style={{ fontSize: 13, fontWeight: 400, color: "#6b7280" }}
          >
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
            fieldLabels={result.fieldLabels ?? undefined}
            showSummary={false}
          />
          {totalPages > 1 && (
            <div style={{ padding: "4px 14px 8px", borderTop: "1px solid #e5e7eb" }}>
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

/* ─── Main page ─── */
export default function CombinedPvaluesPage() {
  // Combined p-values table state
  const [rows, setRows] = useState<CombinedRow[]>([]);
  const [totalRows, setTotalRows] = useState(0);
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState<SortColumn>("fisher_pvalue");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [loading, setLoading] = useState(true);

  // Gene flag filter state — all hidden by default
  const [hideFlags, setHideFlags] = useState<string[]>(
    GENE_FLAG_OPTIONS.map((o) => o.key)
  );

  // Significant rows filter/sort
  const [sigFilterBy, setSigFilterBy] = useState<"pvalue" | "fdr">("pvalue");
  const [sigSortBy, setSigSortBy] = useState<"pvalue" | "fdr">("pvalue");

  // Fetch combined p-values table
  const fetchCombined = useCallback(() => {
    setLoading(true);
    fetch("/api/combined-pvalues-table", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page, pageSize: PAGE_SIZE, sortBy, sortDir, hideFlags }),
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
  }, [page, sortBy, sortDir, hideFlags]);

  const toggleFlag = (flag: string) => {
    setHideFlags((prev) =>
      prev.includes(flag) ? prev.filter((f) => f !== flag) : [...prev, flag]
    );
    setPage(1);
  };

  useEffect(() => {
    fetchCombined();
  }, [fetchCombined]);

  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));

  const handleSort = (col: SortColumn) => {
    if (col === sortBy) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir("asc");
    }
    setPage(1);
  };

  return (
    <>
      <Head>
        <title>Combined P-values — SSPsyGene</title>
      </Head>
      <Header />
      <main
        style={{
          maxWidth: 1200,
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
            maxWidth: 900,
          }}
        >
          Aggregate statistical significance across all datasets. P-values are
          combined using four methods: Fisher and Stouffer (pre-collapsed to one
          p-value per dataset), Cauchy/HMP (using all individual p-values,
          robust to correlation). FDR is Benjamini-Hochberg corrected across all
          genes per method.
        </p>

        {/* Method descriptions */}
        <details
          style={{
            marginBottom: 20,
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            padding: "0 14px",
          }}
        >
          <summary
            style={{
              padding: "10px 0",
              cursor: "pointer",
              fontWeight: 600,
              fontSize: 14,
              color: "#374151",
            }}
          >
            Method descriptions
          </summary>
          <div style={{ paddingBottom: 12, fontSize: 13, color: "#6b7280" }}>
            {Object.entries(METHOD_DESCRIPTIONS).map(([key, desc]) => (
              <div key={key} style={{ marginBottom: 6 }}>
                <strong style={{ color: "#374151" }}>
                  {key === "fisher"
                    ? "Fisher\u2019s method"
                    : key === "stouffer"
                    ? "Stouffer\u2019s method"
                    : key === "cauchy"
                    ? "Cauchy (CCT)"
                    : "Harmonic Mean (HMP)"}
                  :
                </strong>{" "}
                {desc}
              </div>
            ))}
          </div>
        </details>

        {/* Gene category filter */}
        <div
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
          <span style={{ fontWeight: 600, color: "#374151", whiteSpace: "nowrap" }}>
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
              onClick={() => { setHideFlags([]); setPage(1); }}
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
          {hideFlags.length < GENE_FLAG_OPTIONS.length && hideFlags.length > 0 && (
            <button
              onClick={() => { setHideFlags(GENE_FLAG_OPTIONS.map((o) => o.key)); setPage(1); }}
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

        {/* Combined p-values table */}
        <div
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
                fontSize: 13,
              }}
            >
              <thead>
                <tr style={{ background: "#f9fafb" }}>
                  {COMBINED_COLUMNS.map((col) => {
                    const isActive = col.key === sortBy;
                    return (
                      <th
                        key={col.key}
                        onClick={() => handleSort(col.key)}
                        style={{
                          padding: "10px 12px",
                          textAlign: col.right ? "right" : "left",
                          fontWeight: 600,
                          color: isActive ? "#1f2937" : "#6b7280",
                          whiteSpace: "nowrap",
                          cursor: "pointer",
                          userSelect: "none",
                          borderBottom: "1px solid #e5e7eb",
                        }}
                      >
                        {col.label}
                        <span
                          style={{
                            fontSize: 12,
                            marginLeft: 4,
                            color: isActive ? "#1f2937" : "#9ca3af",
                          }}
                        >
                          {isActive
                            ? sortDir === "asc"
                              ? " \u25B2"
                              : " \u25BC"
                            : " \u21C5"}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td
                      colSpan={COMBINED_COLUMNS.length}
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
                {!loading &&
                  rows.map((row, idx) => (
                    <tr
                      key={`${row.human_symbol}-${idx}`}
                      style={{ borderTop: "1px solid #e5e7eb" }}
                    >
                      {COMBINED_COLUMNS.map((col) => {
                        const val = row[col.key as keyof CombinedRow];
                        const isPval =
                          col.mono &&
                          typeof val === "number";
                        const isSignificant =
                          isPval && (val as number) < 0.05;
                        return (
                          <td
                            key={col.key}
                            style={{
                              padding: "8px 12px",
                              fontFamily: col.mono ? "monospace" : undefined,
                              textAlign: col.right ? "right" : "left",
                              color: isSignificant ? "#059669" : "#1f2937",
                              fontWeight: isSignificant ? 600 : 400,
                              whiteSpace: "nowrap",
                            }}
                          >
                            {col.key === "human_symbol" ? (
                              <Link
                                href={`/?searchMode=general&selected=${encodeURIComponent(String(val))}`}
                                style={{
                                  color: "#2563eb",
                                  textDecoration: "none",
                                  fontWeight: 500,
                                }}
                              >
                                {String(val)}
                              </Link>
                            ) : col.mono ? (
                              formatPvalue(val as number | null)
                            ) : (
                              String(val ?? "")
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div style={{ padding: "4px 14px 8px", borderTop: "1px solid #e5e7eb" }}>
              <Pagination
                page={page}
                totalPages={totalPages}
                total={totalRows}
                loading={loading}
                onPageChange={setPage}
              />
            </div>
          )}
        </div>

        {/* Significant rows per dataset */}
        <div
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
            <span style={{ color: "#6b7280" }}>Filter by:</span>
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
              <option value="pvalue">P-value</option>
              <option value="fdr">FDR</option>
            </select>
            <span style={{ color: "#6b7280", marginLeft: 8 }}>Sort by:</span>
            <select
              value={sigSortBy}
              onChange={(e) =>
                setSigSortBy(e.target.value as "pvalue" | "fdr")
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

        <DatasetSections
          filterBy={sigFilterBy}
          sortBy={sigSortBy}
        />
      </main>
      <Footer />
    </>
  );
}

/* ─── Dataset sections loader ─── */
function DatasetSections({
  filterBy,
  sortBy,
}: {
  filterBy: "pvalue" | "fdr";
  sortBy: "pvalue" | "fdr";
}) {
  const [tables, setTables] = useState<DatasetTableMeta[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/dataset-tables-with-pvalues")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setTables(data.tables);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div style={{ color: "#6b7280", padding: "12px 0" }}>
        Loading datasets...
      </div>
    );
  }

  // Filter to tables that have the selected filter column
  const filtered = tables.filter((t) =>
    filterBy === "pvalue" ? t.pvalueColumn : t.fdrColumn
  );

  if (filtered.length === 0) {
    return (
      <div style={{ color: "#6b7280", padding: "12px 0" }}>
        No datasets have a {filterBy === "pvalue" ? "p-value" : "FDR"} column.
      </div>
    );
  }

  return (
    <>
      {filtered.map((t) => (
        <DatasetSection
          key={t.tableName}
          meta={t}
          filterBy={filterBy}
          sortBy={sortBy}
        />
      ))}
    </>
  );
}
