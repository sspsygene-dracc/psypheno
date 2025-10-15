import { useEffect, useState } from "react";
import Head from "next/head";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import DataTable from "@/components/DataTable";

type Dataset = {
  table_name: string;
  description: string | null;
  gene_columns: string;
  gene_species: string;
  display_columns: string;
  scalar_columns: string;
  link_tables: string | null;
};

type DatasetData = {
  tableName: string;
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

  return (
    <>
      <Head>
        <title>All Datasets - SSPsyGene</title>
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
            maxWidth: "1200px",
            width: "100%",
            margin: "0 auto",
            padding: "32px 16px",
            flex: 1,
          }}
        >
          <h1
            style={{
              color: "#f1f5f9",
              fontSize: 32,
              fontWeight: 700,
              marginBottom: 8,
            }}
          >
            All Datasets
          </h1>
          <p style={{ color: "#94a3b8", marginBottom: 24 }}>
            Browse all available datasets in the SSPsyGene database
          </p>

          {loading && (
            <div
              style={{ color: "#e5e7eb", textAlign: "center", marginTop: 32 }}
            >
              Loading datasets...
            </div>
          )}

          {error && (
            <div
              style={{ color: "#ef4444", textAlign: "center", marginTop: 32 }}
            >
              {error}
            </div>
          )}

          {!loading && !error && (
            <div style={{ display: "grid", gap: 24 }}>
              <div
                style={{
                  background: "#0f172a",
                  border: "1px solid #334155",
                  borderRadius: 12,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    padding: "16px",
                    background: "#1e293b",
                    color: "#94a3b8",
                    fontWeight: 600,
                    fontSize: 14,
                  }}
                >
                  Available Datasets ({datasets.length})
                </div>
                <div>
                  {datasets.map((dataset) => (
                    <button
                      key={dataset.table_name}
                      onClick={() => setSelectedDataset(dataset.table_name)}
                      style={{
                        width: "100%",
                        padding: "16px",
                        borderTop: "1px solid #334155",
                        background:
                          selectedDataset === dataset.table_name
                            ? "#1e293b"
                            : "transparent",
                        border: "none",
                        color: "#e5e7eb",
                        textAlign: "left",
                        cursor: "pointer",
                        transition: "background 0.2s ease",
                      }}
                      onMouseEnter={(e) => {
                        if (selectedDataset !== dataset.table_name) {
                          e.currentTarget.style.background = "#1e293b66";
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (selectedDataset !== dataset.table_name) {
                          e.currentTarget.style.background = "transparent";
                        }
                      }}
                    >
                      <div style={{ fontWeight: 600, marginBottom: 4 }}>
                        {dataset.table_name
                          .replace(/_/g, " ")
                          .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1))}
                      </div>
                      <div style={{ fontSize: 14, color: "#94a3b8" }}>
                        Species: {dataset.gene_species} • Columns:{" "}
                        {dataset.display_columns.split(",").length}
                      </div>
                      {dataset.description && (
                        <div
                          style={{
                            fontSize: 13,
                            color: "#94a3b8",
                            marginTop: 6,
                          }}
                        >
                          {dataset.description}
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              </div>

              {selectedDataset && (
                <div
                  style={{
                    background: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: 12,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      padding: "16px",
                      background: "#1e293b",
                      color: "#f1f5f9",
                      fontWeight: 600,
                    }}
                  >
                    {selectedDataset
                      .replace(/_/g, " ")
                      .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1))}
                  </div>

                  {loadingData && (
                    <div
                      style={{
                        padding: 32,
                        textAlign: "center",
                        color: "#e5e7eb",
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
              )}
            </div>
          )}
        </main>
        <Footer />
      </div>
    </>
  );
}
