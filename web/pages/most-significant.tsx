import React, { useEffect, useState, useCallback, type ReactNode } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import GeneInfoBox from "@/components/GeneInfoBox";
import GeneSignificanceSummary, {
  type CombinedPvalues,
  type ContributingTable,
} from "@/components/GeneSignificanceSummary";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import InfoTooltip from "@/components/InfoTooltip";
import DoubleScrollX from "@/components/DoubleScrollX";

const PAGE_SIZE = 10;
const NUM_COLS = 6; // rank, gene, pvalue, tables, pvalues, gene info

type RankedRow = {
  rank: number;
  central_gene_id: number;
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

type Method = "fisher" | "cauchy" | "hmp";
type Regulation = "any" | "up" | "down";

/** Positive "show" flags \u2014 categories of interest. */
const SHOW_FLAG_OPTIONS: { key: string; label: string; href?: string }[] = [
  {
    key: "nimh_priority",
    label: "NIMH Priority genes version 2023-09-21",
    href: "https://www.nimh.nih.gov/research/priority-research-areas/genomics-research",
  },
  { key: "transcription_factor", label: "Transcription Factors" },
  { key: "lncrna", label: "lncRNAs" },
];

/** Negative "hide" flags \u2014 broadly-responsive gene families. */
const HIDE_FLAG_OPTIONS: { key: string; label: string }[] = [
  { key: "heat_shock", label: "Heat shock / chaperones" },
  { key: "mitochondrial_rna", label: "Mitochondrial RNA" },
  { key: "no_hgnc", label: "No HGNC annotation" },
  { key: "non_coding", label: "Non-coding RNA" },
  { key: "pseudogene", label: "Pseudogenes" },
  { key: "ribosomal", label: "Ribosomal proteins" },
  { key: "ubiquitin", label: "Ubiquitin pathway" },
];

/**
 * Conflict map: when a show flag is checked, the listed hide flags
 * should be unchecked (and vice versa) because they are logically
 * mutually exclusive.
 */
const SHOW_HIDE_CONFLICTS: Record<string, string[]> = {
  // lncRNAs are a subset of non-coding RNA
  lncrna: ["non_coding"],
};
const HIDE_SHOW_CONFLICTS: Record<string, string[]> = {
  non_coding: ["lncrna"],
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
    key: "hmp",
    label: "Harmonic Mean P-value (HMP)",
    shortLabel: "HMP",
    description:
      "Computes the weighted harmonic mean of p-values with Landau distribution calibration via R\u2019s harmonicmeanp package. Uses all individual p-values directly. Robust to dependency structure between tests.",
    citation: "Wilson (2019), PNAS",
    doi: "10.1073/pnas.1814092116",
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
    key: "fisher",
    label: "Fisher\u2019s Method",
    shortLabel: "Fisher",
    description:
      "Combines -2\u00B7\u03A3ln(p) across tables. Pre-collapsed to one p-value per table using a Bonferroni-corrected minimum. Particularly sensitive to any single strong signal. Under H\u2080, the test statistic follows a \u03C7\u00B2 distribution with 2k degrees of freedom (k = number of tables).",
    citation: "Fisher (1925), Statistical Methods for Research Workers",
  },
];

function formatPvalue(p: number | null | undefined): string {
  if (p === null || p === undefined) return "\u2014";
  if (p < 1e-300) return "< 1e-300";
  if (p < 0.001) return p.toExponential(3);
  return p.toPrecision(4);
}

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

/* \u2500\u2500\u2500 Main page \u2500\u2500\u2500 */
export default function MostSignificantPage() {
  const router = useRouter();

  const [rows, setRows] = useState<RankedRow[]>([]);
  const [totalRows, setTotalRows] = useState(0);
  const [page, setPage] = useState(1);
  const [method, setMethod] = useState<Method>("hmp");
  const [direction, setDirection] = useState<"target" | "perturbed">("target");
  const [regulation, setRegulation] = useState<Regulation>("any");
  const [loading, setLoading] = useState(true);
  const [noTable, setNoTable] = useState<{ numSourceTables: number } | null>(null);
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
    HIDE_FLAG_OPTIONS.map((o) => o.key),
  );

  // Show-flag filter state \u2014 all checked except lncrna (excluded by default
  // via non_coding hide flag, so showing lncrna would conflict)
  const [showFlags, setShowFlags] = useState<string[]>(
    SHOW_FLAG_OPTIONS.filter((o) => o.key !== "lncrna").map((o) => o.key),
  );
  const [showOther, setShowOther] = useState(true);

  // Gene name search filter
  const [geneSearch, setGeneSearch] = useState("");

  const [assayTypeLabels, setAssayTypeLabels] = useState<
    Record<string, string>
  >({});
  const [assayFilter, setAssayFilter] = useState<string | null>(null);
  const [diseaseFilter, setDiseaseFilter] = useState<string | null>(null);
  const [organismFilter, setOrganismFilter] = useState<string | null>(null);
  const [diseaseTypeLabels, setDiseaseTypeLabels] = useState<
    Record<string, string>
  >({});
  const [organismTypeLabels, setOrganismTypeLabels] = useState<
    Record<string, string>
  >({});
  type CpGroup = {
    assayFilter: string | null;
    diseaseFilter: string | null;
    organismFilter: string | null;
    tableName: string | null;
    numSourceTables: number;
  };
  const [cpGroups, setCpGroups] = useState<CpGroup[]>([]);
  type DatasetTableMeta = {
    tableName: string;
    shortLabel: string | null;
    mediumLabel: string | null;
    longLabel: string | null;
    pvalueColumn: string | null;
    fdrColumn: string | null;
    effectColumn: string | null;
    assay: string[] | null;
    disease: string[] | null;
    organismKey: string[] | null;
  };
  const [datasetTables, setDatasetTables] = useState<DatasetTableMeta[]>([]);

  // Default flag values for URL diffing
  const defaultHideFlags = HIDE_FLAG_OPTIONS.map((o) => o.key);
  const defaultShowFlags = SHOW_FLAG_OPTIONS.filter((o) => o.key !== "lncrna").map((o) => o.key);

  // Initialize state from URL query params on first load
  const [urlInitialized, setUrlInitialized] = useState(false);
  useEffect(() => {
    if (!router.isReady || urlInitialized) return;
    setUrlInitialized(true);
    const q = router.query;
    if (typeof q.method === "string" && ["fisher", "cauchy", "hmp"].includes(q.method)) {
      setMethod(q.method as Method);
    }
    if (typeof q.dir === "string" && ["target", "perturbed"].includes(q.dir)) {
      setDirection(q.dir as "target" | "perturbed");
    }
    if (typeof q.reg === "string" && ["any", "up", "down"].includes(q.reg)) {
      setRegulation(q.reg as Regulation);
    }
    if (typeof q.assay === "string") setAssayFilter(q.assay);
    if (typeof q.disease === "string") setDiseaseFilter(q.disease);
    if (typeof q.organism === "string") setOrganismFilter(q.organism);
    if (typeof q.gene === "string") setGeneSearch(q.gene);
    if (typeof q.page === "string") {
      const p = parseInt(q.page, 10);
      if (p >= 1) setPage(p);
    }
    if (typeof q.show === "string") {
      setShowFlags(q.show === "" ? [] : q.show.split(","));
    }
    if (typeof q.hide === "string") {
      setHideFlags(q.hide === "" ? [] : q.hide.split(","));
    }
    if (typeof q.showOther === "string") {
      setShowOther(q.showOther !== "0");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router.isReady, router.query]);

  // Sync state back to URL (shallow, no navigation). Skip the replace when
  // the next params already equal router.query — that avoids a redundant
  // write on the URL-hydration pass without dropping the user's first
  // interaction (#112 follow-up).
  useEffect(() => {
    if (!router.isReady || !urlInitialized) return;
    const params: Record<string, string> = {};
    if (method !== "hmp") params.method = method;
    if (direction !== "target") params.dir = direction;
    if (regulation !== "any") params.reg = regulation;
    if (assayFilter) params.assay = assayFilter;
    if (diseaseFilter) params.disease = diseaseFilter;
    if (organismFilter) params.organism = organismFilter;
    if (geneSearch) params.gene = geneSearch;
    if (page > 1) params.page = String(page);
    const showSorted = [...showFlags].sort().join(",");
    const defaultShowSorted = [...defaultShowFlags].sort().join(",");
    if (showSorted !== defaultShowSorted) params.show = showFlags.join(",");
    const hideSorted = [...hideFlags].sort().join(",");
    const defaultHideSorted = [...defaultHideFlags].sort().join(",");
    if (hideSorted !== defaultHideSorted) params.hide = hideFlags.join(",");
    if (!showOther) params.showOther = "0";

    const curr = router.query as Record<string, unknown>;
    const keys = new Set([...Object.keys(curr), ...Object.keys(params)]);
    let changed = false;
    for (const k of keys) {
      const a = curr[k];
      const b = params[k];
      if ((a ?? undefined) !== (b ?? undefined)) {
        changed = true;
        break;
      }
    }
    if (!changed) return;

    router.replace({ pathname: router.pathname, query: params }, undefined, { shallow: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [method, direction, regulation, assayFilter, diseaseFilter, organismFilter, geneSearch, page, showFlags, hideFlags, showOther, router.isReady, urlInitialized]);

  useEffect(() => {
    fetch("/api/dataset-tables-with-pvalues")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setAssayTypeLabels(data.assayTypeLabels ?? {});
        setDiseaseTypeLabels(data.diseaseTypeLabels ?? {});
        setOrganismTypeLabels(data.organismTypeLabels ?? {});
        setCpGroups(data.combinedPvalueGroups ?? []);
        setDatasetTables(data.tables ?? []);
      })
      .catch(() => {});
  }, []);

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
        direction,
        regulation,
        hideFlags,
        showFlags,
        showOther,
        assayFilter,
        diseaseFilter,
        organismFilter,
        geneSearch,
      }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setRows(data.rows);
        setTotalRows(data.totalRows);
        setNoTable(
          data.noTable
            ? { numSourceTables: data.numSourceTables ?? 0 }
            : null,
        );
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [
    page,
    method,
    direction,
    regulation,
    hideFlags,
    showFlags,
    showOther,
    assayFilter,
    diseaseFilter,
    organismFilter,
    geneSearch,
  ]);

  const toggleHideFlag = (flag: string) => {
    setHideFlags((prev) => {
      const adding = !prev.includes(flag);
      if (adding) {
        // Uncheck conflicting show flags
        const conflicts = HIDE_SHOW_CONFLICTS[flag];
        if (conflicts) {
          setShowFlags((sf) => sf.filter((f) => !conflicts.includes(f)));
        }
      }
      return adding ? [...prev, flag] : prev.filter((f) => f !== flag);
    });
    setPage(1);
  };

  const toggleShowFlag = (flag: string) => {
    setShowFlags((prev) => {
      const adding = !prev.includes(flag);
      if (adding) {
        // Uncheck conflicting hide flags
        const conflicts = SHOW_HIDE_CONFLICTS[flag];
        if (conflicts) {
          setHideFlags((hf) => hf.filter((f) => !conflicts.includes(f)));
        }
      }
      return adding ? [...prev, flag] : prev.filter((f) => f !== flag);
    });
    setPage(1);
  };

  useEffect(() => {
    if (!urlInitialized) return;
    fetchRanked();
  }, [fetchRanked, urlInitialized]);

  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));

  return (
    <>
      <Head>
        <title>Gene Ranking by Cross-Study Significance &mdash; SSPsyGene</title>
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
          maxWidth: 1000,
          margin: "0 auto",
          padding: "24px 16px",
          color: "#1f2937",
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>
          Gene Ranking by Cross-Study Significance Across All Datasets
        </h1>
        <p
          style={{
            color: "#4b5563",
            fontSize: 15,
            lineHeight: 1.7,
          }}
        >
          This page ranks genes by their aggregate cross-study significance
          across all assays in SSPsyGene. It identifies genes with the strongest
          cumulative p-values across multiple experiments,
          highlighting candidates for follow-up analysis, cross-study
          validation, or pathway enrichment. Use the method selector below to
          compare how rankings change depending on the statistical combination
          approach.
        </p>
        <p
          style={{
            color: "#4b5563",
            fontSize: 15,
            lineHeight: 1.7,
            marginBottom: 20,
          }}
        >
          <strong>Note on combined p-values.</strong> The values below are
          computed from the <strong>raw, unadjusted</strong>&nbsp;per-study
          p-values reported by each dataset (not from the FDR-adjusted
          columns). Combining many small nominal p-values can produce extreme
          combined p-values — that&apos;s expected, and it&apos;s what allows
          the ranking to highlight genes with consistent cross-study evidence.
          See the{" "}
          <Link
            href="/methods"
            style={{ color: "#2563eb", textDecoration: "none", fontWeight: 600 }}
          >
            methods page
          </Link>{" "}
          for the exact pipeline.
        </p>
        <p style={{ marginBottom: 20 }}>
          <Link
            href="/significant-rows"
            style={{ color: "#2563eb", textDecoration: "none", fontWeight: 600 }}
          >
            Browse significant rows (&lt; 0.05) by individual dataset &rarr;
          </Link>
        </p>

        {/* Method + Direction + filter radios (assay / disease / organism) */}
        {cpGroups.length > 0 &&
          (() => {
            const availableAssays = [
              ...new Set(
                cpGroups
                  .filter((g) => g.assayFilter != null)
                  .map((g) => g.assayFilter as string),
              ),
            ].sort();
            const availableDiseases = [
              ...new Set(
                cpGroups
                  .filter((g) => g.diseaseFilter != null)
                  .map((g) => g.diseaseFilter as string),
              ),
            ].sort();
            const availableOrganisms = [
              ...new Set(
                cpGroups
                  .filter((g) => g.organismFilter != null)
                  .map((g) => g.organismFilter as string),
              ),
            ].sort();
            const radioLabelStyle: React.CSSProperties = {
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              cursor: "pointer",
              color: "#4b5563",
              whiteSpace: "nowrap",
              fontSize: 14,
            };
            const directionTooltip =
              "Target: rank each gene by how often its expression or activity is a downstream readout (the gene was measured). " +
              "Perturbed: rank each gene by how often it is the upstream experimentally manipulated gene (CRISPRi/CRISPRa, RNAi, knockout, mutant line).";
            const regulationTooltip =
              "All: combine p-values across every contributing row. " +
              "Up-regulated / Down-regulated: restrict each study to rows whose effect-size column is positive (up) or negative (down) before combining. " +
              "Datasets without an effect-size column drop out under up/down.";
            const filterRowStyle: React.CSSProperties = {
              display: "flex",
              alignItems: "center",
              gap: 14,
              flexWrap: "wrap",
            };
            const filterLabelStyle: React.CSSProperties = {
              fontWeight: 600,
              color: "#374151",
              whiteSpace: "nowrap",
            };
            return (
              <div
                style={{
                  marginBottom: 12,
                  background: "#f9fafb",
                  border: "1px solid #e5e7eb",
                  borderRadius: 8,
                  padding: "10px 14px",
                  fontSize: 13,
                }}
              >
                <div style={{ ...filterRowStyle, marginBottom: 8 }}>
                  <span style={filterLabelStyle}>Ranking method:</span>
                  {METHOD_DESCRIPTIONS.map((m) => (
                    <label key={m.key} style={radioLabelStyle}>
                      <input
                        type="radio"
                        name="method"
                        checked={method === m.key}
                        onChange={() => {
                          setMethod(m.key);
                          setPage(1);
                        }}
                      />
                      {m.shortLabel}
                    </label>
                  ))}
                  <Link
                    href="/methods"
                    style={{
                      color: "#2563eb",
                      textDecoration: "none",
                      fontSize: 12,
                      whiteSpace: "nowrap",
                      marginLeft: "auto",
                    }}
                  >
                    Methods documentation &rarr;
                  </Link>
                </div>
                <div
                  style={{
                    ...filterRowStyle,
                    marginBottom:
                      availableAssays.length > 0 ||
                      availableDiseases.length > 0 ||
                      availableOrganisms.length > 0
                        ? 8
                        : 0,
                  }}
                >
                  <span style={filterLabelStyle}>
                    Direction
                    <InfoTooltip text={directionTooltip} size={13} />:
                  </span>
                  <label style={radioLabelStyle}>
                    <input
                      type="radio"
                      name="direction"
                      checked={direction === "target"}
                      onChange={() => {
                        setDirection("target");
                        setPage(1);
                      }}
                    />
                    Target
                  </label>
                  <label style={radioLabelStyle}>
                    <input
                      type="radio"
                      name="direction"
                      checked={direction === "perturbed"}
                      onChange={() => {
                        setDirection("perturbed");
                        setPage(1);
                      }}
                    />
                    Perturbed
                  </label>
                </div>
                <div style={{ ...filterRowStyle, marginBottom: 8 }}>
                  <span style={filterLabelStyle}>
                    Regulation
                    <InfoTooltip text={regulationTooltip} size={13} />:
                  </span>
                  <label style={radioLabelStyle}>
                    <input
                      type="radio"
                      name="regulation"
                      checked={regulation === "any"}
                      onChange={() => {
                        setRegulation("any");
                        setPage(1);
                      }}
                    />
                    All
                  </label>
                  <label style={radioLabelStyle}>
                    <input
                      type="radio"
                      name="regulation"
                      checked={regulation === "up"}
                      onChange={() => {
                        setRegulation("up");
                        setPage(1);
                      }}
                    />
                    Up-regulated
                  </label>
                  <label style={radioLabelStyle}>
                    <input
                      type="radio"
                      name="regulation"
                      checked={regulation === "down"}
                      onChange={() => {
                        setRegulation("down");
                        setPage(1);
                      }}
                    />
                    Down-regulated
                  </label>
                </div>
                {availableAssays.length > 0 && (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      flexWrap: "wrap",
                      marginBottom:
                        availableDiseases.length > 0 ||
                        availableOrganisms.length > 0
                          ? 8
                          : 0,
                    }}
                  >
                    <span
                      style={{
                        fontWeight: 600,
                        color: "#374151",
                        whiteSpace: "nowrap",
                      }}
                    >
                      Assay type:
                    </span>
                    <label style={radioLabelStyle}>
                      <input
                        type="radio"
                        name="assayFilter"
                        checked={assayFilter === null}
                        onChange={() => {
                          setAssayFilter(null);
                          setPage(1);
                        }}
                      />
                      All
                    </label>
                    {availableAssays.map((key) => (
                      <label key={key} style={radioLabelStyle}>
                        <input
                          type="radio"
                          name="assayFilter"
                          checked={assayFilter === key}
                          onChange={() => {
                            setAssayFilter(key);
                            setPage(1);
                          }}
                        />
                        {assayTypeLabels[key] || key}
                      </label>
                    ))}
                  </div>
                )}
                {availableDiseases.length > 0 && (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      flexWrap: "wrap",
                      marginBottom: availableOrganisms.length > 0 ? 8 : 0,
                    }}
                  >
                    <span
                      style={{
                        fontWeight: 600,
                        color: "#374151",
                        whiteSpace: "nowrap",
                      }}
                    >
                      Disease:
                    </span>
                    <label style={radioLabelStyle}>
                      <input
                        type="radio"
                        name="diseaseFilter"
                        checked={diseaseFilter === null}
                        onChange={() => {
                          setDiseaseFilter(null);
                          setPage(1);
                        }}
                      />
                      All
                    </label>
                    {availableDiseases.map((key) => (
                      <label key={key} style={radioLabelStyle}>
                        <input
                          type="radio"
                          name="diseaseFilter"
                          checked={diseaseFilter === key}
                          onChange={() => {
                            setDiseaseFilter(key);
                            setPage(1);
                          }}
                        />
                        {diseaseTypeLabels[key] || key}
                      </label>
                    ))}
                  </div>
                )}
                {availableOrganisms.length > 0 && (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      flexWrap: "wrap",
                    }}
                  >
                    <span
                      style={{
                        fontWeight: 600,
                        color: "#374151",
                        whiteSpace: "nowrap",
                      }}
                    >
                      Organism:
                    </span>
                    <label style={radioLabelStyle}>
                      <input
                        type="radio"
                        name="organismFilter"
                        checked={organismFilter === null}
                        onChange={() => {
                          setOrganismFilter(null);
                          setPage(1);
                        }}
                      />
                      All
                    </label>
                    {availableOrganisms.map((key) => (
                      <label key={key} style={radioLabelStyle}>
                        <input
                          type="radio"
                          name="organismFilter"
                          checked={organismFilter === key}
                          onChange={() => {
                            setOrganismFilter(key);
                            setPage(1);
                          }}
                        />
                        {organismTypeLabels[key] || key}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}

        {/* Datasets included in current filter */}
        {(() => {
          const filtered = datasetTables.filter((t) => {
            if (!t.pvalueColumn) return false;
            if (regulation !== "any" && !t.effectColumn) return false;
            if (assayFilter && !(t.assay ?? []).includes(assayFilter))
              return false;
            if (diseaseFilter && !(t.disease ?? []).includes(diseaseFilter))
              return false;
            if (
              organismFilter &&
              !(t.organismKey ?? []).includes(organismFilter)
            )
              return false;
            return true;
          });
          if (filtered.length === 0) return null;
          const formatName = (t: DatasetTableMeta) =>
            t.mediumLabel ??
            t.tableName
              .replace(/_/g, " ")
              .replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
          return (
            <div
              style={{
                marginBottom: 12,
                display: "flex",
                flexWrap: "wrap",
                alignItems: "center",
                gap: 6,
                fontSize: 13,
                color: "#6b7280",
              }}
            >
              <span
                style={{ fontWeight: 600, color: "#374151", marginRight: 4 }}
              >
                {filtered.length} dataset{filtered.length !== 1 ? "s" : ""} included:
              </span>
              {filtered.map((t) => (
                <Link
                  key={t.tableName}
                  href={`/full-datasets?select=${encodeURIComponent(t.shortLabel ? t.shortLabel.replace(/\s+/g, "_") : t.tableName)}`}
                  style={{
                    padding: "2px 8px",
                    background: "#eff6ff",
                    color: "#2563eb",
                    borderRadius: 9999,
                    textDecoration: "none",
                    fontSize: 12,
                  }}
                >
                  {formatName(t)}
                </Link>
              ))}
            </div>
          );
        })()}

        {/* Gene selection filter box */}
        <div
          id="gene-filters"
          style={{
            marginBottom: 16,
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            overflow: "hidden",
            fontSize: 13,
          }}
        >
          <div
            style={{
              padding: "8px 14px",
              fontWeight: 600,
              fontSize: 14,
              color: "#374151",
              borderBottom: "1px solid #e5e7eb",
            }}
          >
            Gene selection
          </div>

          {/* Show union of row */}
          <div
            style={{
              padding: "10px 14px",
              display: "flex",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontWeight: 600,
                color: "#374151",
                whiteSpace: "nowrap",
              }}
            >
              Show union of:
            </span>
            {SHOW_FLAG_OPTIONS.map((opt) => (
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
                  checked={showFlags.includes(opt.key)}
                  onChange={() => toggleShowFlag(opt.key)}
                />
                {opt.href ? (
                  <a
                    href={opt.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: "#2563eb", textDecoration: "none" }}
                  >
                    {opt.label}
                  </a>
                ) : (
                  opt.label
                )}
              </label>
            ))}
            <label
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
                checked={showOther}
                onChange={() => {
                  setShowOther((prev) => !prev);
                  setPage(1);
                }}
              />
              All other genes
            </label>
            {!(showFlags.length === SHOW_FLAG_OPTIONS.length && showOther) && (
              <button
                onClick={() => {
                  setShowFlags(SHOW_FLAG_OPTIONS.map((o) => o.key));
                  setShowOther(true);
                  // Handle conflict: lncrna being checked means non_coding must be unchecked
                  setHideFlags((hf) => hf.filter((f) => f !== "non_coding"));
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
                Include all
              </button>
            )}
            {(showFlags.length > 0 || showOther) && (
              <button
                onClick={() => {
                  setShowFlags([]);
                  setShowOther(false);
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
                Include none
              </button>
            )}
          </div>

          {/* Excluding row */}
          <div
            style={{
              padding: "10px 14px",
              display: "flex",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontWeight: 600,
                color: "#374151",
                whiteSpace: "nowrap",
              }}
            >
              Excluding:
            </span>
            {HIDE_FLAG_OPTIONS.map((opt) => (
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
                  onChange={() => toggleHideFlag(opt.key)}
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
                Exclude none
              </button>
            )}
            {hideFlags.length < HIDE_FLAG_OPTIONS.length && (
              <button
                onClick={() => {
                  setHideFlags(HIDE_FLAG_OPTIONS.map((o) => o.key));
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
                Exclude all
              </button>
            )}
          </div>
        </div>

        {/* No-table message for invalid assay\u00D7disease combinations */}
        {noTable && !loading && (
          <div
            style={{
              padding: "16px 20px",
              marginBottom: 16,
              background: "#fef3c7",
              border: "1px solid #fcd34d",
              borderRadius: 8,
              color: "#92400e",
              fontSize: 14,
            }}
          >
            {noTable.numSourceTables === 1 ? (
              <>
                Only one dataset matches this combination — no meta-analysis
                needed.{" "}
                <Link
                  href={`/significant-rows${assayFilter || diseaseFilter || organismFilter ? "?" + [assayFilter && `assay=${encodeURIComponent(assayFilter)}`, diseaseFilter && `disease=${encodeURIComponent(diseaseFilter)}`, organismFilter && `organism=${encodeURIComponent(organismFilter)}`].filter(Boolean).join("&") : ""}`}
                  style={{ color: "#92400e", fontWeight: 600 }}
                >
                  Browse individual dataset results &rarr;
                </Link>
              </>
            ) : (
              "No datasets match this combination."
            )}
          </div>
        )}

        {/* Ranked genes table */}
        {!noTable && <div
          id="ranked-genes-table"
          style={{
            background: "#ffffff",
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            overflow: "hidden",
            marginBottom: 24,
          }}
        >
          <DoubleScrollX>
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
                      borderBottom: "1px solid #e5e7eb",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      Gene
                      <input
                        type="text"
                        placeholder="Filter..."
                        value={geneSearch}
                        onChange={(e) => {
                          setGeneSearch(e.target.value);
                          setPage(1);
                        }}
                        style={{
                          fontSize: 12,
                          fontWeight: 400,
                          padding: "2px 6px",
                          border: "1px solid #d1d5db",
                          borderRadius: 4,
                          width: 100,
                        }}
                      />
                    </div>
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
                            href={`/?${direction}=${encodeURIComponent(row.human_symbol)}`}
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
                            <GeneSignificanceFetcher
                              centralGeneId={row.central_gene_id}
                              direction={direction}
                              regulation={regulation}
                              assayTypeLabels={assayTypeLabels}
                            />
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
          </DoubleScrollX>
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
        </div>}

      </main>
      <Footer />
    </>
  );
}

function GeneSignificanceFetcher({
  centralGeneId,
  direction,
  regulation,
  assayTypeLabels,
}: {
  centralGeneId: number;
  direction: "target" | "perturbed";
  regulation: Regulation;
  assayTypeLabels: Record<string, string>;
}) {
  const [data, setData] = useState<{
    combinedPvalues: CombinedPvalues | null;
    contributingTables: ContributingTable[];
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/combined-pvalues", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ centralGeneId, direction, regulation }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d) return;
        setData({
          combinedPvalues: d.combinedPvalues ?? null,
          contributingTables: d.contributingTables ?? [],
        });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [centralGeneId, direction, regulation]);

  if (!data) return null;
  return (
    <GeneSignificanceSummary
      combinedPvalues={data.combinedPvalues}
      contributingTables={data.contributingTables}
      assayTypeLabels={assayTypeLabels}
    />
  );
}
