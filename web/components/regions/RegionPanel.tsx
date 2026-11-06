import { useState, type CSSProperties, type ReactNode } from "react";
import Link from "next/link";
import type { Dataset } from "@/components/DatasetItem";
import { modelSystemLabel, stageLabel } from "@/lib/dataset-tags";
import {
  IN_VITRO_STROKE,
  SOURCES,
  STUDY_KIND_DESCRIPTIONS,
  STUDY_KIND_LABELS,
  datasetSource,
  olsUrl,
  studyKind,
  type StudyKind,
} from "@/lib/brain-regions";
import type { RegionGenesResponse, RegionGenesTable } from "@/pages/api/region-genes";
import type { GeneRef, GeneRegionsTable } from "@/pages/api/gene-regions";

export type AssayLabeler = (d: Dataset) => string;

/** Gene view: the query and how it matched each table. */
export type GeneInPanel = {
  perturbed: GeneRef | null;
  target: GeneRef | null;
  /** Old ?gene= links: perturbed or measured. */
  either: GeneRef | null;
  roles: ReadonlyMap<string, GeneRegionsTable>;
};

/** The symbol a gene goes by in home-page URLs. */
function urlSym(g: GeneRef): string {
  return g.humanSymbol ?? g.symbol;
}

/** Home-page search link for a perturbed / target gene pair. */
export function geneSearchHref(perturbed: GeneRef | null, target: GeneRef | null): string {
  const q = new URLSearchParams();
  if (perturbed) q.set("perturbed", urlSym(perturbed));
  if (target) q.set("target", urlSym(target));
  return `/?${q.toString()}`;
}

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
  cell_type_reference: { color: "#065f46", background: "#d1fae5" },
  age_association: { color: "#374151", background: "#e5e7eb" },
  observational: { color: "#374151", background: "#f3f4f6" },
  other: { color: "#374151", background: "#f3f4f6" },
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
    <span title={STUDY_KIND_DESCRIPTIONS[kind]} style={{ ...chip, ...KIND_STYLE[kind] }}>
      {STUDY_KIND_LABELS[kind]}
    </span>
  );
}

/** Marks a dataset (or group) as in vitro: dashed violet, like on the drawing. */
export function InVitroChip() {
  return (
    <span
      title="In vitro: placed by the identity the cells were patterned towards, not tissue they came from"
      style={{ ...chip, color: "#5b21b6", background: "#faf9ff", border: `1px dashed ${IN_VITRO_STROKE}` }}
    >
      in vitro
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

export const linkStyle: CSSProperties = { color: "#1d4ed8", textDecoration: "none" };

const MAX_TERMS = 6;

/** "Brodmann (1909) area 22" / "anterior transverse temporal area 41" -> "BA22". */
function shortTermLabel(t: { label: string }): string {
  const m = /^(?:Brodmann \(1909\)|(?:anterior|posterior) transverse temporal) area (\d+)$/.exec(t.label);
  return m ? `BA${m[1]}` : t.label;
}

const ROLE_TEXT: Record<GeneRegionsTable["role"], string> = {
  perturbed: "the gene this dataset knocked out / down, activated or mutated",
  measured: "a readout here; not necessarily significant",
  pair: "perturbed → measured, in one row",
};

function GeneRoleLine({ d, gene }: { d: Dataset; gene: GeneInPanel }) {
  const role = gene.roles.get(d.table_name);
  if (!role) return null;
  const g = gene.either ?? gene.perturbed ?? gene.target;
  if (!g) return null;
  let href: string;
  let text: string;
  let title: string;
  if (role.role === "pair") {
    href = geneSearchHref(gene.perturbed, gene.target);
    text = `${gene.perturbed!.symbol} → ${gene.target!.symbol}`;
    title = `A row of this dataset has ${gene.perturbed!.symbol} as the perturbed gene and ${gene.target!.symbol} as the measured gene`;
  } else if (role.role === "perturbed") {
    href = geneSearchHref(g, null);
    text = `${g.symbol} perturbed`;
    title = `${g.symbol} is in this dataset's perturbed-gene column: it was knocked out / knocked down / activated / mutated here`;
  } else {
    href = geneSearchHref(null, g);
    text = `${g.symbol} measured`;
    title = `${g.symbol} appears as a measured gene here (readout, DE gene, associated gene); not necessarily significant`;
  }
  return (
    <div data-gene-role={role.role} style={{ fontSize: 12, marginTop: 2, color: "#111827" }}>
      <Link
        href={href}
        title={title}
        style={{
          ...chip,
          textDecoration: "none",
          ...(role.role === "measured"
            ? { color: "#374151", background: "#f3f4f6" }
            : { color: "#1e3a8a", background: "#dbeafe" }),
        }}
      >
        {text}
      </Link>{" "}
      <span style={{ color: "#6b7280" }}>{ROLE_TEXT[role.role]}</span>
      {role.nSig !== undefined && role.nMeasured !== undefined && (
        <span style={{ marginLeft: 6 }}>
          · {role.nSig.toLocaleString()} of {role.nMeasured.toLocaleString()} readouts significant
          {role.sigRule ? ` (${sigRuleText(role.sigRule)})` : ""}
        </span>
      )}
    </div>
  );
}

function DatasetRow({
  d,
  inMatrix,
  gene,
}: {
  d: Dataset;
  inMatrix: boolean;
  gene?: GeneInPanel | null;
}) {
  const stage = stageLabel({ stage: d.stage ?? null, stage_detail: d.stage_detail ?? null });
  const allTerms = (d.anatomy ?? []).map(shortTermLabel);
  const terms =
    allTerms.length > MAX_TERMS
      ? [...allTerms.slice(0, MAX_TERMS), `+${allTerms.length - MAX_TERMS} more`]
      : allTerms;
  const inVitro = datasetSource(d) === "in_vitro";
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
      {gene && <GeneRoleLine d={d} gene={gene} />}
      <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
        {inVitro && <span>{modelSystemLabel(d.model_system ?? "")} · </span>}
        {terms.length > 0 && (
          <span title={`Tagged anatomy${inVitro ? " (intended identity)" : ""}: ${allTerms.join(", ")}`}>
            {terms.join(", ")}
          </span>
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
              <Link
                href={`/matrix?tables=${encodeURIComponent(d.table_name)}`}
                style={linkStyle}
                title="This dataset is a column of the overview matrix"
              >
                matrix
              </Link>
            </>
          )}
        </span>
      </div>
    </li>
  );
}

/**
 * Datasets grouped by source (the page's toggle chips), then by assay. The
 * in-vitro group is boxed in dashed violet, as on the drawing.
 */
export function DatasetGroups({
  datasets,
  assayLabel,
  matrixTables,
  gene = null,
}: {
  datasets: Dataset[];
  assayLabel: AssayLabeler;
  matrixTables: ReadonlySet<string>;
  gene?: GeneInPanel | null;
}) {
  return (
    <div>
      {SOURCES.map((src) => {
        const inSource = datasets.filter((d) => datasetSource(d) === src.key);
        if (inSource.length === 0) return null;
        const assays = Array.from(new Set(inSource.map(assayLabel))).sort();
        const inVitro = src.key === "in_vitro";
        return (
          <div
            key={src.key}
            data-source={src.key}
            style={{
              marginBottom: 10,
              ...(inVitro
                ? {
                    border: `1.5px dashed ${IN_VITRO_STROKE}`,
                    background: "#faf9ff",
                    borderRadius: 8,
                    padding: "6px 10px",
                  }
                : {}),
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 700, color: inVitro ? "#5b21b6" : "#1f2937" }}>
              {src.label} <span style={{ fontWeight: 400, color: "#6b7280" }}>({inSource.length})</span>
            </div>
            {inVitro && (
              <div style={{ fontSize: 12, color: "#6b7280" }}>
                Intended identity (what the cells were patterned towards), not tissue.
              </div>
            )}
            {assays.map((a) => (
              <div key={a} style={{ marginLeft: 10 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#374151", marginTop: 4 }}>{a}</div>
                <ul style={{ margin: 0, padding: 0 }}>
                  {inSource
                    .filter((d) => assayLabel(d) === a)
                    .map((d) => (
                      <DatasetRow key={d.table_name} d={d} inMatrix={matrixTables.has(d.table_name)} gene={gene} />
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
        {d && datasetSource(d) === "in_vitro" && (
          <>
            {" "}
            <InVitroChip />
          </>
        )}
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
          " The case-vs-control datasets above show which genes differ in cases, not what perturbing a gene does."}
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
