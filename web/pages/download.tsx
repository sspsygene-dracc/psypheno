import { useEffect, useState } from "react";
import Head from "next/head";
import Link from "next/link";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import DatasetLinkAnchor from "@/components/DatasetLinkAnchor";
import DatasetToc, { useAssayGroups, type TocItem } from "@/components/DatasetToc";
import type { Dataset } from "@/components/DatasetItem";

type DatasetsResponse = { datasets: Dataset[] };

function datasetTitle(d: Dataset): string {
  if (d.medium_label) return d.medium_label;
  if (d.short_label) return d.short_label;
  return d.table_name.replace(/_/g, " ");
}

function parseCsvList(s: string | null): string[] {
  if (!s) return [];
  return s.split(",").map((x) => x.trim()).filter(Boolean);
}

const downloadBtn: React.CSSProperties = {
  display: "inline-block",
  padding: "6px 12px",
  background: "#ffffff",
  border: "1px solid #d1d5db",
  borderRadius: 8,
  fontSize: 13,
  fontWeight: 500,
  color: "#1f2937",
  textDecoration: "none",
  whiteSpace: "nowrap",
};

const primaryDownloadBtn: React.CSSProperties = {
  ...downloadBtn,
  background: "#2563eb",
  borderColor: "#2563eb",
  color: "#ffffff",
};

const RSnippet = `# In R
manifest <- read.delim("manifest.tsv", stringsAsFactors = FALSE)
tbl      <- read.delim("tables/SCZ_Risk_Arrayed_RNAseq_supp_1.tsv",
                       stringsAsFactors = FALSE)
head(tbl)`;

const PySnippet = `# In Python (pandas)
import pandas as pd
manifest = pd.read_csv("manifest.tsv", sep="\\t")
tbl      = pd.read_csv("tables/SCZ_Risk_Arrayed_RNAseq_supp_1.tsv", sep="\\t")`;

export default function DownloadPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [assayTypeLabels, setAssayTypeLabels] = useState<Record<string, string>>(
    {},
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showToc, setShowToc] = useState(false);

  useEffect(() => {
    Promise.all([
      fetch("/api/full-datasets").then((r) => {
        if (!r.ok) throw new Error(`Failed: ${r.status}`);
        return r.json() as Promise<DatasetsResponse>;
      }),
      fetch("/api/assay-types").then((r) =>
        r.ok ? r.json() : { assayTypeLabels: {} },
      ),
    ])
      .then(([data, types]) => {
        setDatasets(data.datasets);
        setAssayTypeLabels(types.assayTypeLabels ?? {});
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : "Failed to load datasets";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, []);

  // Match GeneResults: only show the side TOC on wide enough viewports.
  useEffect(() => {
    const mql = window.matchMedia("(min-width: 900px)");
    setShowToc(mql.matches);
    const handler = (e: MediaQueryListEvent) => setShowToc(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  const tocItems: TocItem[] = datasets.map((d) => ({
    tableName: d.table_name,
    shortLabel: d.short_label,
    mediumLabel: d.medium_label,
    longLabel: d.long_label,
    assay: parseCsvList(d.assay),
  }));
  const groups = useAssayGroups(tocItems, assayTypeLabels);
  const datasetByTableName = new Map(datasets.map((d) => [d.table_name, d]));

  return (
    <>
      <Head>
        <title>Downloads &mdash; SSPsyGene</title>
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
            maxWidth: "1200px",
            width: "100%",
            margin: "0 auto",
            padding: "32px 16px",
            flex: 1,
          }}
        >
          <h1 style={{ color: "#1f2937", fontSize: 32, fontWeight: 700, marginBottom: 8 }}>
            Downloads
          </h1>
          <p style={{ color: "#4b5563", marginBottom: 24, lineHeight: 1.5 }}>
            Bulk downloads of the SSPsyGene Knowledge Base data for offline
            analysis. Gene identifiers have been resolved to gene symbols (HGNC
            for human, MGI for mouse) where mappings exist (
            <Link href="/gene-parser" style={{ color: "#2563eb" }}>
              how does this work?
            </Link>
            ).
          </p>

          <section
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 12,
              padding: 20,
              marginBottom: 32,
              background: "#f9fafb",
            }}
          >
            <h2 style={{ fontSize: 20, fontWeight: 700, marginTop: 0, marginBottom: 12, color: "#1f2937" }}>
              Full database
            </h2>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
              <a href="/api/download/all-tables.zip" style={primaryDownloadBtn}>
                All tables (TSV ZIP)
              </a>
              <a href="/api/download/sspsygene.db" style={downloadBtn}>
                SQLite database
              </a>
              <a href="/api/download/ensembl_to_symbol.tsv" style={downloadBtn}>
                Ensembl ID &harr; symbol map (TSV)
              </a>
              <a href="/api/download/manifest.tsv" style={downloadBtn}>
                Manifest (TSV)
              </a>
              <a href="/api/download/README.txt" style={downloadBtn}>
                README
              </a>
            </div>
            <p style={{ color: "#4b5563", fontSize: 14, marginTop: 0, marginBottom: 0 }}>
              The TSV ZIP contains one tab-separated file per dataset, plus
              per-table metadata YAMLs and a manifest. The SQLite database is
              the same file the website queries; it includes the central gene
              table and many-to-many link tables for advanced users.
            </p>
            <details style={{ marginTop: 16 }}>
              <summary style={{ cursor: "pointer", color: "#374151", fontSize: 14, fontWeight: 600 }}>
                Sample loading code
              </summary>
              <div style={{ display: "grid", gap: 12, marginTop: 12 }}>
                <pre style={preStyle}><code>{RSnippet}</code></pre>
                <pre style={preStyle}><code>{PySnippet}</code></pre>
              </div>
            </details>
          </section>

          <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 12, color: "#1f2937" }}>
            Per-dataset downloads
          </h2>
          <p style={{ color: "#4b5563", marginBottom: 8, fontSize: 14 }}>
            Click <em>Data (TSV)</em> for the full table,{" "}
            <em>Metadata (YAML)</em> for column descriptions, citation, and
            source links, or — when present —{" "}
            <em>Preprocessing (YAML)</em> for the per-step record of how the
            raw data was cleaned before loading.
          </p>
          <details style={{ marginBottom: 16 }}>
            <summary
              style={{
                cursor: "pointer",
                color: "#374151",
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              About preprocessing provenance
            </summary>
            <div
              style={{
                marginTop: 8,
                padding: "10px 12px",
                background: "#f9fafb",
                border: "1px solid #e5e7eb",
                borderRadius: 8,
                fontSize: 13,
                color: "#374151",
                lineHeight: 1.55,
              }}
            >
              <p style={{ marginTop: 0 }}>
                Each dataset's <em>Preprocessing (YAML)</em> file lists every
                action the data wrangler's <code>preprocess.py</code> script
                applied to the raw data — gene-symbol rescues, dropped rows,
                renamed columns, custom transforms — in the order they
                executed. Read it to audit how a published table was turned
                into the table you can search and download here.
              </p>
              <p style={{ marginBottom: 0 }}>
                Common fields you'll see:
              </p>
              <ul style={{ marginTop: 6, marginBottom: 0, paddingLeft: 20 }}>
                <li>
                  <code>step: clean_gene_column</code> — gene-symbol resolution
                  for one column. <code>counts.passed_through</code> = rows
                  whose original symbol resolved directly;{" "}
                  <code>counts.rescued_excel</code> = rows where
                  Excel-mangled values like <code>9-Sep</code> were repaired
                  to <code>SEPTIN9</code>; <code>counts.rescued_make_unique</code>{" "}
                  = R <code>make.unique</code> suffixes
                  (<code>MATR3.1 → MATR3</code>) stripped;{" "}
                  <code>counts.rescued_manual_alias</code> = wrangler-curated
                  successor map hits (<code>NOV → CCN3</code>);{" "}
                  <code>counts.rescued_ensembl_map</code> = ENSG/ENSMUSG IDs
                  resolved to symbols; <code>counts.unresolved</code> = rows
                  the cleaner could not resolve (kept as-is). The first ~10
                  unresolved values appear in <code>sample_unresolved</code>{" "}
                  for inspection. See{" "}
                  <Link href="/gene-parser" style={{ color: "#2563eb" }}>
                    the gene-parser doc
                  </Link>{" "}
                  for what each rescue step does.
                </li>
                <li>
                  <code>step: dropna</code> /{" "}
                  <code>step: filter_rows</code> — rows removed by a
                  predicate. <code>rows_before</code> /{" "}
                  <code>rows_after</code> / <code>dropped</code> tell you the
                  exact counts.
                </li>
                <li>
                  <code>step: rename</code> /{" "}
                  <code>step: drop_columns</code> /{" "}
                  <code>step: reorder</code> — schema reshape.
                </li>
                <li>
                  <code>step: transform_column</code> — a one-off custom
                  string fixup; the <code>description</code> field explains
                  what was done.
                </li>
                <li>
                  <code>step: read_csv</code> / <code>step: write_csv</code> —
                  bookends recording the source filename and the final column
                  list.
                </li>
              </ul>
              <p style={{ marginTop: 8, marginBottom: 0 }}>
                Each cleaned table also keeps two extra columns for
                row-level provenance: <code>&lt;gene_col&gt;_raw</code> (the
                original value before cleaning) and{" "}
                <code>_&lt;gene_col&gt;_resolution</code> (the per-row tag
                — <code>passed_through</code>, <code>rescued_excel</code>,
                <code>unresolved</code>, etc.). Cross-reference those with
                the YAML to investigate any specific row. Full walkthrough:{" "}
                <Link href="/gene-parser" style={{ color: "#2563eb" }}>
                  how the gene parser works
                </Link>
                .
              </p>
            </div>
          </details>

          {loading && <div style={{ color: "#6b7280" }}>Loading datasets...</div>}
          {error && <div style={{ color: "#dc2626" }}>{error}</div>}

          {!loading && !error && (
            <div
              style={{
                display: "flex",
                gap: 24,
                alignItems: "flex-start",
              }}
            >
              {showToc && groups.length > 0 && (
                <DatasetToc groups={groups} anchorPrefix="download-" />
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                {groups.map((group) => {
                  const hasMultipleGroups = groups.length > 1;
                  return (
                    <div key={group.assayKey}>
                      {hasMultipleGroups && (
                        <div
                          id={`assay-group-${group.assayKey}`}
                          style={{
                            marginTop: 24,
                            marginBottom: 6,
                            padding: "8px 0",
                            borderBottom: "2px solid #dbeafe",
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            scrollMarginTop: 16,
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
                            {group.items.length} dataset
                            {group.items.length !== 1 ? "s" : ""}
                          </span>
                        </div>
                      )}
                      <div style={{ display: "grid", gap: 12, marginTop: 12 }}>
                        {group.items.map((item) => {
                          const d = datasetByTableName.get(item.tableName);
                          if (!d) return null;
                          return <DatasetRow key={d.table_name} dataset={d} />;
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}

function DatasetRow({ dataset }: { dataset: Dataset }) {
  const sourceLinks = dataset.links;
  const tn = dataset.table_name;
  const title = datasetTitle(dataset);
  const slug = dataset.short_label
    ? dataset.short_label.replace(/\s+/g, "_")
    : tn;

  return (
    <div
      id={`download-${tn}`}
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 10,
        padding: "14px 16px",
        background: "#ffffff",
        scrollMarginTop: 16,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ flex: "1 1 280px", minWidth: 0 }}>
          <Link
            href={`/full-datasets?open=${encodeURIComponent(slug)}`}
            style={{
              fontSize: 15,
              fontWeight: 600,
              color: "#1f2937",
              textDecoration: "none",
            }}
          >
            {title}
          </Link>
          {dataset.organism && (
            <span style={{ color: "#6b7280", fontSize: 13, marginLeft: 8 }}>
              · {dataset.organism}
            </span>
          )}
          {dataset.publication_year && (
            <span style={{ color: "#6b7280", fontSize: 13, marginLeft: 8 }}>
              · {dataset.publication_year}
            </span>
          )}
          {dataset.description && (
            <div
              style={{
                color: "#6b7280",
                fontSize: 13,
                marginTop: 4,
                lineHeight: 1.4,
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }}
            >
              {dataset.description}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", flexShrink: 0 }}>
          <a
            href={`/api/download/tables/${encodeURIComponent(tn)}.tsv`}
            style={downloadBtn}
            title={`Download ${tn}.tsv`}
          >
            Data (TSV)
          </a>
          <a
            href={`/api/download/metadata/${encodeURIComponent(tn)}.yaml`}
            style={downloadBtn}
            title={`Download ${tn}.yaml metadata`}
          >
            Metadata (YAML)
          </a>
          {dataset.has_preprocessing && (
            <a
              href={`/api/download/preprocessing/${encodeURIComponent(tn)}.yaml`}
              style={downloadBtn}
              title={`Download ${tn}.yaml preprocessing provenance — every action the wrangler's preprocess.py applied to this table`}
            >
              Preprocessing (YAML)
            </a>
          )}
        </div>
      </div>
      {sourceLinks.length > 0 && (
        <div
          style={{
            marginTop: 10,
            paddingTop: 8,
            borderTop: "1px solid #f3f4f6",
            fontSize: 13,
            color: "#6b7280",
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            alignItems: "baseline",
          }}
        >
          <span style={{ fontWeight: 500 }}>Source:</span>
          {sourceLinks.map((link) => (
            <DatasetLinkAnchor
              key={link.url}
              link={link}
              tooltipSize={13}
              anchorStyle={{ wordBreak: "break-all" }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

const preStyle: React.CSSProperties = {
  background: "#1f2937",
  color: "#f9fafb",
  padding: 12,
  borderRadius: 8,
  fontSize: 12,
  overflowX: "auto",
  margin: 0,
  lineHeight: 1.5,
};
