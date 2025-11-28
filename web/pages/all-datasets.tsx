import { useEffect, useState } from "react";
import Head from "next/head";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import DataTable from "@/components/DataTable";

type Dataset = {
  table_name: string;
  short_label: string | null;
  long_label: string | null;
  description: string | null;
  gene_columns: string;
  gene_species: string;
  display_columns: string;
  scalar_columns: string;
  link_tables: string | null;
  links: string | null;
  categories: string | null;
  organism: string | null;
  publication_first_author: string | null;
  publication_last_author: string | null;
  publication_year: number | null;
  publication_journal: string | null;
  publication_doi: string | null;
};

type DatasetData = {
  tableName: string;
  shortLabel: string | null;
  longLabel: string | null;
  description: string | null;
  organism: string | null;
  links: string[];
  categories: string[];
  publication: {
    firstAuthor: string | null;
    lastAuthor: string | null;
    year: number | null;
    journal: string | null;
    doi: string | null;
    pmid: string | null;
  } | null;
  displayColumns: string[];
  rows: Record<string, unknown>[];
  totalRows?: number;
};

export default function AllDatasets() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [datasetData, setDatasetData] = useState<DatasetData | null>(null);
  const [loadingData, setLoadingData] = useState(false);

  useEffect(() => {
    const fetchDatasets = async () => {
      try {
        const res = await fetch("/api/all-datasets");
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const data = await res.json();
        setDatasets(data.datasets);
      } catch (e: any) {
        setError(e?.message || "Failed to load datasets");
      } finally {
        setLoading(false);
      }
    };
    fetchDatasets();
  }, []);

  useEffect(() => {
    if (!selectedDataset) {
      setDatasetData(null);
      return;
    }

    const fetchDatasetData = async () => {
      setLoadingData(true);
      try {
        const res = await fetch(
          `/api/dataset-data?tableName=${encodeURIComponent(selectedDataset)}`
        );
        if (!res.ok) throw new Error(`Failed: ${res.status}`);
        const data = await res.json();
        setDatasetData(data);
      } catch (e: any) {
        setError(e?.message || "Failed to load dataset data");
      } finally {
        setLoadingData(false);
      }
    };
    fetchDatasetData();
  }, [selectedDataset]);

  useEffect(() => {
    if (!loadingData && datasetData && selectedDataset) {
      const anchor = document.getElementById("dataset-table-top");
      if (anchor) {
        anchor.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  }, [loadingData, datasetData, selectedDataset]);

  return (
    <>
      <Head>
        <title>All Datasets - SSPsyGene</title>
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
          <h1
            style={{
              color: "#1f2937",
              fontSize: 32,
              fontWeight: 700,
              marginBottom: 8,
            }}
          >
            All Datasets
          </h1>
          <p style={{ color: "#6b7280", marginBottom: 24 }}>
            Browse all available datasets in the SSPsyGene database
          </p>

          {loading && (
            <div
              style={{ color: "#6b7280", textAlign: "center", marginTop: 32 }}
            >
              Loading datasets...
            </div>
          )}

          {error && (
            <div
              style={{ color: "#dc2626", textAlign: "center", marginTop: 32 }}
            >
              {error}
            </div>
          )}

          {!loading && !error && (
            <div style={{ display: "grid", gap: 24 }}>
              <div
                style={{
                  background: "#ffffff",
                  border: "1px solid #e5e7eb",
                  borderRadius: 12,
                  overflowX: "auto",
                  overflowY: "hidden",
                }}
              >
                <div
                  style={{
                    padding: "16px",
                    background: "#f9fafb",
                    color: "#6b7280",
                    fontWeight: 600,
                    fontSize: 14,
                  }}
                >
                  Available Datasets ({datasets.length})
                </div>
                <div>
                  {datasets.map((dataset) => {
                    const prettifiedName = dataset.table_name
                      .replace(/_/g, " ")
                      .replace(
                        /\w\S*/g,
                        (txt) => txt.charAt(0).toUpperCase() + txt.slice(1)
                      );
                    const heading = dataset.short_label ?? prettifiedName;
                    return (
                      <div
                        key={dataset.table_name}
                        style={{
                          width: "100%",
                          padding: "16px",
                          borderTop: "1px solid #e5e7eb",
                          background: "transparent",
                          color: "#1f2937",
                          transition: "background 0.2s ease",
                          userSelect: "text",
                          WebkitUserSelect: "text",
                          MozUserSelect: "text",
                          msUserSelect: "text",
                          display: "flex",
                          flexWrap: "wrap",
                          gap: 12,
                          alignItems: "flex-start",
                          justifyContent: "space-between",
                          boxSizing: "border-box",
                          maxWidth: "100%",
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLDivElement).style.background =
                            "#f3f4f6";
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLDivElement).style.background =
                            "transparent";
                        }}
                      >
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 600, marginBottom: 4 }}>
                            {heading}
                          </div>
                          {dataset.long_label && (
                            <div
                              style={{
                                fontSize: 14,
                                color: "#4b5563",
                                marginBottom: 4,
                              }}
                            >
                              {dataset.long_label}
                            </div>
                          )}
                          <div style={{ fontSize: 14, color: "#6b7280" }}>
                            <b>
                              {dataset.display_columns.split(",").length}{" "}
                              Columns:
                            </b>{" "}
                            {dataset.display_columns.split(",").join(", ")}
                          </div>
                          <div
                            style={{
                              fontSize: 13,
                              color: "#6b7280",
                              marginTop: 4,
                            }}
                          >
                            {dataset.organism && (
                              <span>
                                <b>Organism:</b> {dataset.organism}
                              </span>
                            )}
                            {!dataset.organism && dataset.gene_species && (
                              <span>
                                <b>Species:</b> {dataset.gene_species}
                              </span>
                            )}
                          </div>
                          {dataset.categories && (
                            <div
                              style={{
                                fontSize: 12,
                                color: "#4b5563",
                                marginTop: 4,
                                display: "flex",
                                flexWrap: "wrap",
                                gap: 6,
                              }}
                            >
                              {dataset.categories
                                .split(",")
                                .map((c) => c.trim())
                                .filter(Boolean)
                                .map((cat) => (
                                  <span
                                    key={cat}
                                    style={{
                                      backgroundColor: "#f3f4f6",
                                      borderRadius: 9999,
                                      padding: "2px 8px",
                                    }}
                                  >
                                    {cat}
                                  </span>
                                ))}
                            </div>
                          )}
                          {dataset.description && (
                            <div
                              style={{
                                fontSize: 14,
                                color: "#6b7280",
                                marginTop: 6,
                              }}
                            >
                              <b>Description:</b> {dataset.description}
                            </div>
                          )}
                          {(dataset.publication_first_author ||
                            dataset.publication_year ||
                            dataset.publication_journal ||
                            dataset.publication_doi) && (
                            <div
                              style={{
                                fontSize: 13,
                                color: "#6b7280",
                                marginTop: 4,
                              }}
                            >
                              <b>Publication:</b>{" "}
                              {dataset.publication_first_author
                                ? `${dataset.publication_first_author}${
                                    dataset.publication_last_author
                                      ? " & " + dataset.publication_last_author
                                      : " et al."
                                  }`
                                : ""}
                              {dataset.publication_year
                                ? ` (${dataset.publication_year})`
                                : ""}
                              {dataset.publication_journal
                                ? `, ${dataset.publication_journal}`
                                : ""}
                            </div>
                          )}
                        </div>
                        <div style={{ flexShrink: 0 }}>
                          <button
                            onClick={() =>
                              setSelectedDataset(dataset.table_name)
                            }
                            style={{
                              background: "#ffffff",
                              color: "#1f2937",
                              border: "1px solid #d1d5db",
                              borderRadius: 8,
                              padding: "8px 12px",
                              cursor: "pointer",
                              whiteSpace: "nowrap",
                            }}
                            aria-label={`Show first 100 rows of ${dataset.table_name}`}
                          >
                            Show first 100 rows
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {selectedDataset && (
                <>
                  <div id="dataset-table-top" />
                  <div
                    style={{
                      background: "#ffffff",
                      border: "1px solid #e5e7eb",
                      borderRadius: 12,
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        padding: "16px",
                        background: "#f9fafb",
                        color: "#1f2937",
                        fontWeight: 600,
                      }}
                    >
                      {datasetData?.shortLabel ??
                        selectedDataset
                          ?.replace(/_/g, " ")
                          .replace(
                            /\w\S*/g,
                            (txt) => txt.charAt(0).toUpperCase() + txt.slice(1)
                          )}
                    </div>

                    {datasetData?.longLabel && (
                      <div
                        style={{
                          padding: "8px 16px",
                          background: "#f9fafb",
                          color: "#4b5563",
                          borderTop: "1px solid #e5e7eb",
                          fontSize: 14,
                        }}
                      >
                        {datasetData.longLabel}
                      </div>
                    )}

                    {datasetData?.description && (
                      <div
                        style={{
                          padding: "8px 16px 0 16px",
                          color: "#6b7280",
                          fontSize: 14,
                        }}
                      >
                        <b>Description:</b> {datasetData.description}
                      </div>
                    )}

                    {datasetData &&
                      (datasetData.organism ||
                        (datasetData.categories?.length ?? 0) > 0 ||
                        (datasetData.links?.length ?? 0) > 0 ||
                          datasetData.publication) && (
                        <div
                          style={{
                            padding: "8px 16px 0 16px",
                            color: "#6b7280",
                            fontSize: 13,
                            display: "grid",
                            gap: 4,
                          }}
                        >
                          {datasetData.organism && (
                            <div>
                              <b>Organism:</b> {datasetData.organism}
                            </div>
                          )}
                          {datasetData.categories?.length > 0 && (
                            <div>
                              <b>Categories:</b>{" "}
                              {datasetData.categories.join(", ")}
                            </div>
                          )}
                          {datasetData.publication && (
                            <div>
                              <b>Publication:</b>{" "}
                              {[
                                datasetData.publication.firstAuthor,
                                datasetData.publication.lastAuthor,
                              ]
                                .filter(Boolean)
                                .join(" & ")}
                              {datasetData.publication.year
                                ? ` (${datasetData.publication.year})`
                                : ""}
                              {datasetData.publication.journal
                                ? `, ${datasetData.publication.journal}`
                                : ""}
                              {datasetData.publication.doi
                                ? `, DOI: ${datasetData.publication.doi}`
                                : ""}
                            </div>
                          )}
                          {datasetData.links?.length > 0 && (
                            <div>
                              <b>Links:</b>{" "}
                              {datasetData.links.map((url) => (
                                <a
                                  key={url}
                                  href={url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  style={{ marginRight: 8 }}
                                >
                                  {url}
                                </a>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                    {loadingData && (
                      <div
                        style={{
                          padding: 32,
                          textAlign: "center",
                          color: "#6b7280",
                        }}
                      >
                        Loading data...
                      </div>
                    )}

                    {!loadingData && datasetData && (
                      <DataTable
                        columns={datasetData.displayColumns}
                        rows={datasetData.rows}
                        maxRows={100}
                        totalRows={datasetData.totalRows}
                      />
                    )}
                  </div>
                </>
              )}
            </div>
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}
