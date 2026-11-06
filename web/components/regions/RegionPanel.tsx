import { useState, type CSSProperties, type ReactNode } from "react";
import Link from "next/link";
import type { Dataset } from "@/components/DatasetItem";
import {
  MODEL_SYSTEM_LABELS,
  modelSystemLabel,
  stageLabel,
} from "@/lib/dataset-tags";
import {
  STUDY_KIND_LABELS,
  olsUrl,
  studyKind,
  type StudyKind,
} from "@/lib/brain-regions";
import type { RegionGenesResponse, RegionGenesTable } from "@/pages/api/region-genes";

export type AssayLabeler = (d: Dataset) => string;

/** /full-datasets?select=<short label>, the same slug that page writes. */
export function datasetHref(d: Dataset): string {
  const slug = d.short_label ? d.short_label.replace(/\s+/g, "_") : d.table_name;
  return `/full-datasets?select=${encodeURIComponent(slug)}`;
}

export function datasetTitle(d: Dataset): string {
  return d.medium_label ?? d.short_label ?? d.table_name;
}

const KIND_STYLE: Record<StudyKind, { color: string; background: string }> = {
  perturbation: { color: "#1e3a8a", background: "#dbeafe" },
  case_control: { color: "#92400e", background: "#fef3c7" },
  observational: { color: "#374151", background: "#f3f4f6" },
  other: { color: "#374151", background: "#f3f4f6" },
};

const KIND_TITLE: Record<StudyKind, string> = {
  perturbation: "Genes were experimentally perturbed (knockout, CRISPRi/a, knockdown, ...)",
  case_control:
    "Cases (postmortem tissue or patient-derived lines, e.g. autism) compared with controls; no gene was perturbed",
  observational: "No manipulation (markers, networks, ...)",
  other: "Experiment type not tagged",
};

const chip: CSSProperties = {
  borderRadius: 9999,
  fontSize: 11,
  padding: "0 7px",
  lineHeight: 1.6,
  whiteSpace: "nowrap",
};

export function KindChip({ kind }: { kind: StudyKind }) {
  return (
    <span title={KIND_TITLE[kind]} style={{ ...chip, ...KIND_STYLE[kind] }}>
      {STUDY_KIND_LABELS[kind]}
    </span>
  );
}

const sectionHead: CSSProperties = {
  fontSize: 13,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: 0.4,
  color: "#4b5563",
  margin: "18px 0 8px",
};

const linkStyle: CSSProperties = { color: "#1d4ed8", textDecoration: "none" };

const MAX_TERMS = 6;

/** "Brodmann (1909) area 22" / "anterior transverse temporal area 41" -> "BA22". */
function shortTermLabel(t: { label: string }): string {
  const m = /^(?:Brodmann \(1909\)|(?:anterior|posterior) transverse temporal) area (\d+)$/.exec(t.label);
  return m ? `BA${m[1]}` : t.label;
}

function DatasetRow({
  d,
  inMatrix,
}: {
  d: Dataset;
  inMatrix: boolean;
}) {
  const stage = stageLabel({ stage: d.stage ?? null, stage_detail: d.stage_detail ?? null });
  const allTerms = (d.anatomy ?? []).map(shortTermLabel);
  const terms =
    allTerms.length > MAX_TERMS
      ? [...allTerms.slice(0, MAX_TERMS), `+${allTerms.length - MAX_TERMS} more`]
      : allTerms;
  return (
    <li
      data-table={d.table_name}
      style={{ padding: "6px 0", borderTop: "1px solid #f1f3f5", listStyle: "none" }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "baseline" }}>
        <Link href={datasetHref(d)} style={{ ...linkStyle, fontWeight: 600, fontSize: 14 }}>
          {datasetTitle(d)}
        </Link>
        <KindChip kind={studyKind(d)} />
      </div>
      <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
        {terms.length > 0 && (
          <span title={`Tagged anatomy: ${allTerms.join(", ")}`}>{terms.join(", ")}</span>
        )}
        {stage && <span>{terms.length > 0 ? " · " : ""}{stage}</span>}
        <span>
          {" · "}
          <Link href={datasetHref(d)} style={linkStyle}>
            table
          </Link>
          {inMatrix && (
            <>
              {" · "}
              <Link href="/matrix" style={linkStyle} title="This dataset is a column of the overview matrix">
                matrix
              </Link>
            </>
          )}
        </span>
      </div>
    </li>
  );
}

/** Datasets grouped by model system (vocabulary order), then by assay. */
export function DatasetGroups({
  datasets,
  assayLabel,
  matrixTables,
}: {
  datasets: Dataset[];
  assayLabel: AssayLabeler;
  matrixTables: ReadonlySet<string>;
}) {
  const systems = Object.keys(MODEL_SYSTEM_LABELS).filter((ms) =>
    datasets.some((d) => d.model_system === ms),
  );
  return (
    <div>
      {systems.map((ms) => {
        const inSystem = datasets.filter((d) => d.model_system === ms);
        const assays = Array.from(new Set(inSystem.map(assayLabel))).sort();
        return (
          <div key={ms} style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#5b21b6" }}>
              {modelSystemLabel(ms)} <span style={{ fontWeight: 400, color: "#6b7280" }}>({inSystem.length})</span>
            </div>
            {assays.map((a) => (
              <div key={a} style={{ marginLeft: 10 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#374151", marginTop: 4 }}>{a}</div>
                <ul style={{ margin: 0, padding: 0 }}>
                  {inSystem
                    .filter((d) => assayLabel(d) === a)
                    .map((d) => (
                      <DatasetRow key={d.table_name} d={d} inMatrix={matrixTables.has(d.table_name)} />
                    ))}
                </ul>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

const GENES_SHOWN = 12;

function sigRuleText(rule: string): string {
  return rule === "nominal_p<0.05" ? "nominal p < 0.05" : "FDR < 0.05";
}

function GeneBlock({ t, d }: { t: RegionGenesTable; d: Dataset | undefined }) {
  const [all, setAll] = useState(false);
  const shown = all ? t.genes : t.genes.slice(0, GENES_SHOWN);
  return (
    <div data-gene-block={t.sourceTable} style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 600 }}>
        {d ? datasetTitle(d) : t.sourceTable}
      </div>
      <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }}>
        {t.nGenes.toLocaleString()} perturbed gene{t.nGenes === 1 ? "" : "s"} · readouts
        significant ({sigRuleText(t.sigRule)}) / measured
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {shown.map((g) => (
          <Link
            key={g.centralGeneId}
            href={g.symbol ? `/?perturbed=${encodeURIComponent(g.symbol)}` : "#"}
            title={`${g.symbol ?? "?"}: ${g.nSig.toLocaleString()} of ${g.nMeasured.toLocaleString()} readouts significant`}
            style={{
              fontSize: 12,
              padding: "1px 7px",
              border: "1px solid #e5e7eb",
              borderRadius: 6,
              color: "#111827",
              textDecoration: "none",
              background: g.nSig > 0 ? "#ffffff" : "#f9fafb",
            }}
          >
            <span style={{ fontWeight: 600 }}>{g.symbol ?? "?"}</span>{" "}
            <span style={{ color: "#6b7280" }}>
              {g.nSig.toLocaleString()} / {g.nMeasured.toLocaleString()}
            </span>
          </Link>
        ))}
        {t.genes.length > GENES_SHOWN && (
          <button
            type="button"
            onClick={() => setAll(!all)}
            style={{
              fontSize: 12,
              padding: "1px 8px",
              border: "1px solid #d1d5db",
              borderRadius: 6,
              background: "#f9fafb",
              cursor: "pointer",
            }}
          >
            {all ? "show fewer" : `show all ${t.genes.length.toLocaleString()}`}
          </button>
        )}
      </div>
    </div>
  );
}

/** Perturbed genes (from the overview matrix) for the perturbation tables. */
export function PerturbedGenes({
  datasets,
  genes,
  loading,
}: {
  datasets: Dataset[];
  genes: RegionGenesResponse | null;
  loading: boolean;
}) {
  const perturbation = datasets.filter((d) => studyKind(d) === "perturbation");
  if (perturbation.length === 0) {
    const caseControl = datasets.some((d) => studyKind(d) === "case_control");
    return (
      <p style={{ fontSize: 13, color: "#4b5563", margin: 0 }}>
        No perturbation data here.
        {caseControl &&
          " The datasets above compare cases with controls: they show which genes differ in cases, not what perturbing a gene does."}
      </p>
    );
  }
  if (loading || !genes) return <p style={{ fontSize: 13, color: "#6b7280" }}>Loading perturbed genes…</p>;
  if (!genes.available) {
    return (
      <p style={{ fontSize: 13, color: "#6b7280" }}>
        The overview matrix has not been built on this site, so perturbed-gene counts are unavailable.
      </p>
    );
  }
  const byTable = new Map(datasets.map((d) => [d.table_name, d]));
  const tables = genes.tables.filter((t) => perturbation.some((d) => d.table_name === t.sourceTable));
  const missing = perturbation.filter((d) => !tables.some((t) => t.sourceTable === d.table_name));
  return (
    <div>
      {tables.map((t) => (
        <GeneBlock key={t.sourceTable} t={t} d={byTable.get(t.sourceTable)} />
      ))}
      {missing.length > 0 && (
        <p style={{ fontSize: 12, color: "#6b7280", margin: "4px 0 0" }}>
          Not in the overview matrix (no per-gene readout counts):{" "}
          {missing.map((d, i) => (
            <span key={d.table_name}>
              {i > 0 && ", "}
              <Link href={datasetHref(d)} style={linkStyle}>
                {datasetTitle(d)}
              </Link>
            </span>
          ))}
        </p>
      )}
    </div>
  );
}

export function PanelSection({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <section>
      <h3 style={sectionHead}>{title}</h3>
      {children}
    </section>
  );
}

export function UberonLink({ id }: { id: string }) {
  return (
    <a href={olsUrl(id)} target="_blank" rel="noopener noreferrer" style={{ ...linkStyle, fontSize: 12 }}>
      {id}
    </a>
  );
}
