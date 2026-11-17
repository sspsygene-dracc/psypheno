import type { GetServerSideProps } from "next";
import { REGIONS_ENABLED } from "@/lib/features";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import SearchBar from "@/components/SearchBar";
import InfoTooltip from "@/components/InfoTooltip";
import type { Dataset } from "@/components/DatasetItem";
import BrainDrawing, { type RegionPaint, type Ring } from "@/components/regions/BrainDrawing";
import { REGION_DRAWINGS, type RegionDrawing } from "@/lib/region-drawings";
import {
  DatasetGroups,
  InVitroChip,
  KindChip,
  PanelSection,
  PerturbedGenes,
  UberonLink,
  datasetTitle,
  datasetHref,
  geneSearchHref,
  linkStyle,
  type AssayLabeler,
  type GeneInPanel,
} from "@/components/regions/RegionPanel";
import {
  ALL_SOURCES,
  BRAIN_VIEWS,
  BRAIN_VIEW_LABELS,
  COUNT_BINS,
  IN_VITRO_ONLY_FILL,
  IN_VITRO_STROKE,
  REGIONS,
  SOURCES,
  countInk,
  datasetSource,
  datasetsWithGene,
  filterBySources,
  findRegion,
  matrixTablesHref,
  parseSources,
  regionFill,
  regionTallies,
  sourcesParam,
  splitInVitro,
  studyKind,
  type BrainView,
  type RegionDef,
  type SourceKey,
  type StudyKind,
} from "@/lib/brain-regions";
import { fullDatasetsRegionHref } from "@/lib/dataset-tags";
import type { SearchSuggestion } from "@/state/SearchSuggestion";
import type { RegionGenesResponse } from "@/pages/api/region-genes";
import type { GeneRef, GeneRegionsResponse } from "@/pages/api/gene-regions";
import type { Modality } from "@/pages/api/modalities";

/**
 * /regions — brain-region dataset navigator. One human brain (lateral and
 * medial views of the DKT atlas) is the default; every dataset with an
 * anatomy tag is mapped onto it through its UBERON terms, whatever species or
 * model system it comes from (lib/brain-regions.ts has the rules). A mouse
 * brain (Allen P56 sagittal section) is the optional second view. Source
 * chips pick which datasets are counted; in-vitro data keep a dashed violet
 * style everywhere so they never read as tissue. Datasets tagged above the
 * drawn level sit in "coarse" buckets next to the drawing; datasets with no
 * brain region at all in "Not region-specific".
 *
 * URL: ?view=human|mouse &side=lateral|medial &sources=<SourceKey,...>
 * &region=<region key> &perturbed=SYMBOL &target=SYMBOL (gene view, same
 * semantics as the home page search) &gene=SYMBOL (old links: perturbed or
 * measured). Old ?species=mouse and ?view=lateral|medial links still work.
 */

const card: CSSProperties = {
  background: "#ffffff",
  border: "1px solid #e5e7eb",
  borderRadius: 10,
  padding: 16,
};

function parseView(q: Record<string, unknown>): BrainView {
  const v = q.view ?? q.species;
  return v === "mouse" ? "mouse" : "human";
}

function countBy<T>(items: T[], key: (t: T) => string): Array<[string, number]> {
  const m = new Map<string, number>();
  for (const it of items) m.set(key(it), (m.get(key(it)) ?? 0) + 1);
  return Array.from(m.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Drawing label count: "3" (tissue), or "3 + 2" (tissue + in vitro; see the legend). */
function countText(tissue: number, inVitro: number): string {
  return inVitro === 0 ? String(tissue) : `${tissue} + ${inVitro}`;
}

/** A SearchBar value for a symbol from the URL (the bar only shows its text). */
function urlSuggestion(symbol: string | null): SearchSuggestion | null {
  if (!symbol) return null;
  return {
    centralGeneId: 0,
    searchQuery: symbol,
    displayLabel: symbol,
    humanSymbol: symbol,
    mouseSymbols: null,
    humanSynonyms: null,
    mouseSynonyms: null,
    datasetCount: 0,
    kind: "gene",
  };
}

const str = (v: unknown) => (typeof v === "string" && v !== "" ? v : null);

// Prototype page: 404 unless the build enables it (lib/features.ts).
export const getServerSideProps: GetServerSideProps = async () =>
  REGIONS_ENABLED ? { props: {} } : { notFound: true };

export default function RegionsPage() {
  const router = useRouter();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [assayTypes, setAssayTypes] = useState<Record<string, string>>({});
  const [modalities, setModalities] = useState<Modality[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bucketHover, setBucketHover] = useState<string | null>(null);
  const [genes, setGenes] = useState<RegionGenesResponse | null>(null);
  const [genesLoading, setGenesLoading] = useState(false);
  const [geneData, setGeneData] = useState<GeneRegionsResponse | null>(null);
  const [geneLoading, setGeneLoading] = useState(false);

  const view = parseView(router.query);
  const drawings: readonly RegionDrawing[] = REGION_DRAWINGS[view];
  const sideParam = str(router.query.side) ?? str(router.query.view);
  const drawing = drawings.find((d) => d.key === sideParam) ?? drawings[0];
  const sources = useMemo(() => parseSources(router.query.sources), [router.query.sources]);

  const qPerturbed = str(router.query.perturbed);
  const qTarget = str(router.query.target);
  const qGene = qPerturbed || qTarget ? null : str(router.query.gene);
  const geneMode = !!(qPerturbed || qTarget || qGene);
  const geneKey = geneMode ? `${qPerturbed ?? ""}|${qTarget ?? ""}|${qGene ?? ""}` : "";

  const regionParam = str(router.query.region);
  const selection: RegionDef | null = useMemo(() => {
    if (!regionParam) return null;
    return (
      findRegion(view, regionParam) ??
      REGIONS[view].find((x) => x.uberon === regionParam && x.kind === "drawn") ??
      null
    );
  }, [regionParam, view]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch("/api/full-datasets").then((r) => {
        if (!r.ok) throw new Error(`Failed: ${r.status}`);
        return r.json();
      }),
      fetch("/api/assay-types").then((r) => (r.ok ? r.json() : { assayTypes: {} })),
      fetch("/api/modalities").then((r) => (r.ok ? r.json() : { modalities: [] })),
    ])
      .then(([ds, at, mo]) => {
        if (cancelled) return;
        setDatasets(ds.datasets ?? []);
        setAssayTypes(at.assayTypes ?? {});
        setModalities(mo.modalities ?? []);
      })
      .catch((e) => !cancelled && setError(e?.message || "Failed to load datasets"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  // Modality label for a dataset's (first) assay, as the matrix names it.
  const assayLabel: AssayLabeler = useMemo(() => {
    const byAssay = new Map<string, string>();
    for (const m of modalities) for (const a of m.assayTypes) if (!byAssay.has(a)) byAssay.set(a, m.label);
    return (d: Dataset) => {
      const a = (d.assay ?? "").split(",")[0]?.trim() ?? "";
      if (!a) return "Other";
      return byAssay.get(a) ?? assayTypes[a] ?? a;
    };
  }, [modalities, assayTypes]);

  // Gene view: fetch which tables the query matches, then run the same
  // region logic on just those tables.
  useEffect(() => {
    if (!geneKey) {
      setGeneData(null);
      return;
    }
    const ctrl = new AbortController();
    const params = new URLSearchParams();
    if (qPerturbed) params.set("perturbed", qPerturbed);
    if (qTarget) params.set("target", qTarget);
    if (qGene) params.set("gene", qGene);
    setGeneLoading(true);
    fetch(`/api/gene-regions?${params.toString()}`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j: GeneRegionsResponse) => setGeneData(j))
      .catch((e) => {
        if (e?.name !== "AbortError") {
          setGeneData({ perturbed: null, target: null, either: null, notFound: [], tables: [], excluded: [] });
        }
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setGeneLoading(false);
      });
    return () => ctrl.abort();
    // geneKey covers qPerturbed / qTarget / qGene.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geneKey]);

  const geneRoles = useMemo(
    () => new Map((geneData?.tables ?? []).map((t) => [t.table, t])),
    [geneData],
  );
  const gene: GeneInPanel | null =
    geneMode && geneData && geneData.notFound.length === 0
      ? { perturbed: geneData.perturbed, target: geneData.target, either: geneData.either, roles: geneRoles }
      : null;

  // Datasets before / after the source toggle (gene view: only the gene's tables).
  const candidates = useMemo(
    () =>
      (geneMode ? (geneData ? datasetsWithGene(datasets, geneRoles) : []) : datasets).filter(
        (d) => datasetSource(d) !== null,
      ),
    [geneMode, geneData, datasets, geneRoles],
  );
  const viewDatasets = useMemo(() => filterBySources(candidates, sources), [candidates, sources]);
  const sourceCounts = useMemo(() => {
    const m = new Map<SourceKey, number>();
    for (const d of candidates) {
      const s = datasetSource(d);
      if (s) m.set(s, (m.get(s) ?? 0) + 1);
    }
    return m;
  }, [candidates]);

  const tallies = useMemo(() => regionTallies(viewDatasets, view), [viewDatasets, view]);
  const coarse = REGIONS[view].filter((r) => r.kind === "coarse");
  const noneRegion = REGIONS[view].find((r) => r.kind === "none")!;

  const setQuery = (patch: Record<string, string | null>) => {
    const q: Record<string, string> = {};
    for (const [k, v] of Object.entries({ ...router.query, ...patch })) {
      if (typeof v === "string" && v !== "") q[k] = v;
    }
    // Old-style params are rewritten to the current ones.
    delete q.species;
    if (q.view && q.view !== "human" && q.view !== "mouse") delete q.view;
    if (q.view === "human") delete q.view;
    router.replace({ pathname: router.pathname, query: q }, undefined, { shallow: true, scroll: false });
  };
  const selectRegion = (key: string | null) => setQuery({ region: key });

  const toggleSource = (s: SourceKey) => {
    const next = new Set(sources);
    if (next.has(s)) next.delete(s);
    else next.add(s);
    if (next.size === 0) return; // keep at least one
    setQuery({ sources: sourcesParam(next) });
  };

  // Datasets the panel lists, and so the tables whose genes it needs.
  const panel = selection ? (tallies.get(selection.key) ?? { specific: [], broader: [] }) : null;
  const panelTablesKey = panel
    ? Array.from(new Set([...panel.specific, ...panel.broader].map((d) => d.table_name))).sort().join(",")
    : "";

  useEffect(() => {
    if (!panelTablesKey) {
      setGenes(null);
      return;
    }
    const ctrl = new AbortController();
    setGenesLoading(true);
    fetch(`/api/region-genes?tables=${encodeURIComponent(panelTablesKey)}`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j: RegionGenesResponse) => setGenes(j))
      .catch((e) => {
        if (e?.name !== "AbortError") setGenes({ available: false, tables: [], notInMatrix: [] });
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setGenesLoading(false);
      });
    return () => ctrl.abort();
  }, [panelTablesKey]);

  const matrixTables = useMemo(
    () => new Set((genes?.tables ?? []).map((t) => t.sourceTable)),
    [genes],
  );

  const rings: Ring[] = useMemo(() => {
    const out: Ring[] = [];
    for (const r of REGIONS[view]) {
      if (r.kind !== "drawn") continue;
      if (splitInVitro(tallies.get(r.key)?.specific ?? []).inVitro.length > 0) {
        out.push({ key: r.key, style: "invitro" });
      }
    }
    const bucket = findRegion(view, bucketHover ?? "") ?? (selection?.kind === "coarse" ? selection : null);
    for (const k of bucket?.covers ?? []) out.push({ key: k, style: "cover" });
    if (selection?.kind === "drawn") out.push({ key: selection.key, style: "selected" });
    return out;
  }, [view, tallies, bucketHover, selection]);

  const paint = (key: string): RegionPaint => {
    const { tissue, inVitro } = splitInVitro(tallies.get(key)?.specific ?? []);
    const label = findRegion(view, key)?.label ?? key;
    return {
      fill: regionFill(tissue.length, inVitro.length),
      ink: tissue.length > 0 ? countInk(tissue.length) : "#1f2937",
      countText: countText(tissue.length, inVitro.length),
      ariaLabel: `${label}: ${plural(tissue.length, "tissue dataset")}${
        inVitro.length ? `, ${inVitro.length} in vitro` : ""
      }`,
    };
  };

  const noneTally = tallies.get(noneRegion.key)!;

  return (
    <>
      <Head>
        <title>Brain regions &mdash; SSPsyGene</title>
      </Head>
      <Header />
      <main style={{ maxWidth: 1280, margin: "0 auto", padding: "24px 16px", color: "#1f2937" }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 6 }}>Brain regions</h1>
        <p style={{ fontSize: 14, color: "#4b5563", marginTop: 0, maxWidth: 960 }}>
          {view === "human" ? (
            <>
              Where in the brain the datasets come from, shown on one human brain. Every dataset
              with an anatomy tag is placed on the matching human region, whatever species or
              model it comes from: anatomy terms (UBERON) are cross-species, so mouse cortex lands
              on the human cortex and a cortical organoid on the cortex it was patterned towards.
            </>
          ) : (
            <>
              The same datasets mapped onto mouse anatomy instead: human lobe and Brodmann-area
              data land on the mouse cerebral cortex, organoids on the region they were patterned
              towards.
            </>
          )}{" "}
          A region is coloured by its number of <strong>tissue</strong> datasets; <DashedSample />{" "}
          marks <strong>in-vitro</strong> data (organoids, iPSC-derived cells, cultures), which
          are an intended identity, not tissue. Datasets that name no{" "}
          {view === "human" ? "lobe" : "drawn structure"} sit in the boxes under the drawing
          instead of colouring every region. Click a region for its datasets.
        </p>

        <GeneQuery
          perturbed={qPerturbed}
          target={qTarget}
          onChange={(p) => setQuery({ ...p, gene: null, region: null })}
        />
        {geneMode && (
          <GeneBanner
            loading={geneLoading}
            data={geneData}
            query={{ perturbed: qPerturbed, target: qTarget, gene: qGene }}
            datasets={datasets}
            shown={viewDatasets}
            candidates={candidates}
          />
        )}

        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
          <div role="tablist" aria-label="Brain" style={{ display: "inline-flex", gap: 4 }}>
            {BRAIN_VIEWS.map((v) => (
              <button
                key={v}
                role="tab"
                type="button"
                aria-selected={v === view}
                onClick={() => setQuery({ view: v === "human" ? null : v, side: null, region: null })}
                style={toggleStyle(v === view)}
              >
                {BRAIN_VIEW_LABELS[v]}
              </button>
            ))}
          </div>
          {drawings.length > 1 && (
            <div role="group" aria-label="Side" style={{ display: "inline-flex", gap: 4, marginLeft: 12 }}>
              {drawings.map((d) => (
                <button
                  key={d.key}
                  type="button"
                  aria-pressed={d.key === drawing.key}
                  onClick={() => setQuery({ side: d.key === drawings[0].key ? null : d.key })}
                  style={toggleStyle(d.key === drawing.key)}
                >
                  {d.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <div
          role="group"
          aria-label="Data sources"
          style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 12, flexWrap: "wrap", fontSize: 13 }}
        >
          <span style={{ fontWeight: 600, color: "#374151" }}>Show data from:</span>
          {SOURCES.map((s) => {
            const on = sources.has(s.key);
            const inVitro = s.key === "in_vitro";
            return (
              <button
                key={s.key}
                type="button"
                data-source-chip={s.key}
                aria-pressed={on}
                title={s.description}
                onClick={() => toggleSource(s.key)}
                style={{
                  padding: "4px 10px",
                  borderRadius: 9999,
                  fontSize: 13,
                  cursor: "pointer",
                  fontWeight: 600,
                  border: inVitro ? `1.5px dashed ${IN_VITRO_STROKE}` : "1.5px solid #9ca3af",
                  background: on ? (inVitro ? "#ede9fe" : "#1f2937") : "#ffffff",
                  color: on ? (inVitro ? "#4c1d95" : "#ffffff") : "#6b7280",
                }}
              >
                {on ? "✓ " : ""}
                {s.label} ({sourceCounts.get(s.key) ?? 0})
              </button>
            );
          })}
          {sources.size < ALL_SOURCES.length && (
            <button type="button" onClick={() => setQuery({ sources: null })} style={{ ...linkButton }}>
              all sources
            </button>
          )}
        </div>

        {error && <p style={{ color: "#b91c1c" }}>{error}</p>}

        <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 560px", minWidth: 320, display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={card}>
              <div style={{ position: "relative" }}>
                <BrainDrawing
                  drawing={drawing}
                  paint={paint}
                  rings={rings}
                  selectedKey={selection?.kind === "drawn" ? selection.key : null}
                  onHover={() => {}}
                  onSelect={(k) => selectRegion(k)}
                />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                <Legend />
                <span style={{ fontSize: 12, color: "#6b7280" }}>
                  {drawing.caption}
                  {drawing.credit && (
                    <>
                      {" · "}
                      <a href={drawing.credit.href} target="_blank" rel="noopener noreferrer" style={{ color: "#4b5563" }}>
                        {drawing.credit.text}
                      </a>
                    </>
                  )}
                </span>
              </div>
              <CoarseBuckets
                view={view}
                buckets={coarse}
                tallies={tallies}
                selectedKey={selection?.key ?? null}
                onHover={setBucketHover}
                onSelect={selectRegion}
              />
            </div>
            <NotRegionSpecific
              region={noneRegion}
              datasets={noneTally.specific}
              selected={selection?.key === noneRegion.key}
              onSelect={() => selectRegion(noneRegion.key)}
            />
          </div>

          <div style={{ flex: "1 1 420px", minWidth: 320 }}>
            <div style={card} aria-live="polite">
              {loading ? (
                <p style={{ margin: 0, color: "#6b7280" }}>Loading datasets…</p>
              ) : selection && panel ? (
                <SelectionPanel
                  region={selection}
                  view={view}
                  specific={panel.specific}
                  broader={panel.broader}
                  assayLabel={assayLabel}
                  matrixTables={matrixTables}
                  genes={genes}
                  genesLoading={genesLoading}
                  gene={gene}
                  onClose={() => selectRegion(null)}
                />
              ) : (
                <Intro datasets={viewDatasets} view={view} geneMode={geneMode} />
              )}
            </div>
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}

const linkButton: CSSProperties = {
  background: "none",
  border: "none",
  color: "#1d4ed8",
  cursor: "pointer",
  fontSize: 13,
  padding: "2px 4px",
  textDecoration: "underline",
};

function toggleStyle(active: boolean): CSSProperties {
  return {
    padding: "5px 12px",
    background: active ? "#1f2937" : "#ffffff",
    color: active ? "#ffffff" : "#1f2937",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
  };
}

function DashedSample() {
  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-block",
        width: 14,
        height: 11,
        borderRadius: 3,
        background: IN_VITRO_ONLY_FILL,
        border: `2px dashed ${IN_VITRO_STROKE}`,
        verticalAlign: "-1px",
      }}
    />
  );
}

/**
 * The gene view's two inputs, as on the home page: a perturbed gene, a
 * measured (target) gene, or both for a perturbation → readout pair.
 */
function GeneQuery({
  perturbed,
  target,
  onChange,
}: {
  perturbed: string | null;
  target: string | null;
  onChange: (p: { perturbed?: string | null; target?: string | null }) => void;
}) {
  const sym = (s: SearchSuggestion | null) => (s ? (s.humanSymbol ?? s.mouseSymbols?.[0] ?? s.searchQuery) : null);
  // Stable objects: SearchBar resets its text whenever `value` changes identity.
  const values = {
    perturbed: useMemo(() => urlSuggestion(perturbed), [perturbed]),
    target: useMemo(() => urlSuggestion(target), [target]),
  };
  const label: CSSProperties = { fontSize: 13, fontWeight: 600, color: "#374151", display: "flex", alignItems: "center", marginBottom: 4 };
  const field = (
    which: "perturbed" | "target",
    title: string,
    help: string,
    value: string | null,
  ) => (
    <div style={{ flex: "1 1 260px", minWidth: 240, maxWidth: 340 }}>
      <div style={label}>
        <span>{title}</span>
        <InfoTooltip size={13} text={help} />
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <div style={{ flex: 1 }}>
          <SearchBar
            placeholder={which === "perturbed" ? "e.g. SHANK3" : "e.g. CNR1"}
            value={values[which]}
            extraBody={{ direction: which }}
            onSelect={(s) => onChange({ [which]: sym(s) })}
          />
        </div>
        {/* Always rendered (hidden when empty) so the input doesn't resize. */}
        <button
          type="button"
          onClick={() => onChange({ [which]: null })}
          aria-label={`Clear ${title.toLowerCase()}`}
          aria-hidden={!value}
          tabIndex={value ? 0 : -1}
          style={{ ...linkButton, visibility: value ? "visible" : "hidden" }}
        >
          Clear
        </button>
      </div>
    </div>
  );
  return (
    <section
      aria-label="Gene view"
      style={{ ...card, background: "#f8fafc", padding: "10px 14px", marginBottom: 12, display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-end" }}
    >
      {field(
        "perturbed",
        "Perturbed gene",
        "Regions of the datasets in which this gene is a perturbed gene: listed in the dataset's perturbed-gene column, i.e. knocked out, knocked down, activated, overexpressed or carried as a variant. Postmortem tissue studies perturb nothing, so they never match here.",
        perturbed,
      )}
      {field(
        "target",
        "Measured (target) gene",
        "Regions of the datasets in which this gene appears as a measured gene: a readout, differentially expressed gene or associated gene. Appearing does not mean significant.",
        target,
      )}
      <p style={{ flex: "1 1 260px", fontSize: 12, color: "#4b5563", margin: 0 }}>
        Fill in one field to see where a gene was <strong>perturbed</strong> or <strong>measured</strong>; fill in both for
        the datasets that perturbed the first and measured the second (the home page&rsquo;s pair search).
      </p>
    </section>
  );
}

function GeneBanner({
  loading,
  data,
  query,
  datasets,
  shown,
  candidates,
}: {
  loading: boolean;
  data: GeneRegionsResponse | null;
  query: { perturbed: string | null; target: string | null; gene: string | null };
  datasets: Dataset[];
  /** The gene's tables that pass the source toggle. */
  shown: Dataset[];
  /** The gene's tables on the page (any source). */
  candidates: Dataset[];
}) {
  const box: CSSProperties = {
    ...card,
    background: "#f8fafc",
    padding: "8px 12px",
    marginBottom: 12,
    fontSize: 13,
    lineHeight: 1.5,
  };
  if (loading || !data) return <div style={box}>Looking up the gene…</div>;
  if (data.notFound.length > 0) {
    return (
      <div role="note" style={{ ...box, background: "#fffbeb", borderColor: "#fde68a" }}>
        No gene matches {data.notFound.map((s) => `“${s}”`).join(" or ")}.
      </div>
    );
  }
  const p: GeneRef | null = data.perturbed;
  const t: GeneRef | null = data.target;
  const e: GeneRef | null = data.either;
  const onPage = new Set(candidates.map((d) => d.table_name));
  const offPage = data.tables.filter((x) => !onPage.has(x.table) && datasets.some((d) => d.table_name === x.table)).length;
  const hiddenBySource = candidates.length - shown.length;
  const title = (table: string) => {
    const d = datasets.find((x) => x.table_name === table);
    return d ? datasetTitle(d) : table;
  };
  let what: React.ReactNode;
  if (p && t) {
    what = (
      <>
        Datasets with a row where <strong>{p.symbol}</strong> was <strong>perturbed</strong> and{" "}
        <strong>{t.symbol}</strong> was <strong>measured</strong> as a readout
      </>
    );
  } else if (p) {
    what = (
      <>
        Datasets in which <strong>{p.symbol}</strong> was <strong>perturbed</strong>: it is in the dataset&rsquo;s
        perturbed-gene column (knocked out, knocked down, activated, overexpressed or carried as a variant)
      </>
    );
  } else if (t) {
    what = (
      <>
        Datasets in which <strong>{t.symbol}</strong> was <strong>measured</strong>: it appears as a readout,
        differentially expressed or associated gene (not necessarily significant)
      </>
    );
  } else {
    what = (
      <>
        Datasets in which <strong>{e?.symbol ?? query.gene}</strong> was perturbed <em>or</em> measured (an older
        link; use the fields above to choose)
      </>
    );
  }
  const searchHref = p || t ? geneSearchHref(p, t) : e ? geneSearchHref(e, null) : "/";
  return (
    <div role="status" data-gene-banner style={box}>
      {what}: <strong>{shown.length}</strong> on this page
      {hiddenBySource > 0 && <> ({hiddenBySource} more hidden by the source chips)</>}.
      {offPage > 0 && ` ${offPage} more have no anatomy tag (e.g. curated resources) and are not shown here.`}{" "}
      <Link href={searchHref} style={{ color: "#1d4ed8" }}>
        all results in the gene search
      </Link>
      {data.excluded.length > 0 && (
        <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
          Not counted as perturbed:{" "}
          {data.excluded.map((x, i) => (
            <span key={x.table}>
              {i > 0 && "; "}
              {title(x.table)}, where the gene is {x.reason}
            </span>
          ))}
          .
        </div>
      )}
    </div>
  );
}

function Legend() {
  const swatch = (bg: string, border = "1px solid #d1d5db"): CSSProperties => ({
    width: 14,
    height: 14,
    borderRadius: 3,
    background: bg,
    border,
    boxSizing: "border-box",
  });
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#4b5563", flexWrap: "wrap" }}>
      Tissue datasets:
      {COUNT_BINS.map((b) => (
        <span key={b.label} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
          <span aria-hidden="true" style={swatch(b.fill)} />
          {b.label}
        </span>
      ))}
      <span style={{ display: "inline-flex", alignItems: "center", gap: 3, marginLeft: 6 }}>
        <span aria-hidden="true" style={swatch("#ffffff", `2px dashed ${IN_VITRO_STROKE}`)} />
        has in-vitro data
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
        <span aria-hidden="true" style={swatch(IN_VITRO_ONLY_FILL, `2px dashed ${IN_VITRO_STROKE}`)} />
        in vitro only
      </span>
      <span>· labels: tissue (+ in vitro)</span>
    </span>
  );
}

/**
 * The coarse buckets: datasets tagged above the drawn level. Each shows the
 * same colour scale as the regions; hovering outlines what it spans.
 */
function CoarseBuckets({
  view,
  buckets,
  tallies,
  selectedKey,
  onHover,
  onSelect,
}: {
  view: BrainView;
  buckets: readonly RegionDef[];
  tallies: Map<string, { specific: Dataset[]; broader: Dataset[] }>;
  selectedKey: string | null;
  onHover: (key: string | null) => void;
  onSelect: (key: string) => void;
}) {
  return (
    <section aria-label="Broader than one region" style={{ marginTop: 14, borderTop: "1px solid #e5e7eb", paddingTop: 10 }}>
      <h2 style={{ fontSize: 14, fontWeight: 700, margin: "0 0 2px" }}>
        {view === "human" ? "No lobe given" : "No subregion given"}
      </h2>
      <p style={{ fontSize: 12, color: "#6b7280", margin: "0 0 8px" }}>
        {view === "human"
          ? "These datasets are tagged with the whole cortex, forebrain or brain, not a lobe, so they are not counted in any lobe. Hover to outline what they span."
          : "These datasets are tagged with the whole forebrain or brain, not a structure on the drawing, so they are not counted in any region. Hover to outline what they span."}
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: 8 }}>
        {buckets.map((b) => {
          const items = tallies.get(b.key)?.specific ?? [];
          const { tissue, inVitro } = splitInVitro(items);
          const selected = selectedKey === b.key;
          const fill = regionFill(tissue.length, inVitro.length);
          return (
            <button
              key={b.key}
              type="button"
              data-bucket={b.key}
              aria-pressed={selected}
              onMouseEnter={() => onHover(b.key)}
              onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(b.key)}
              onBlur={() => onHover(null)}
              onClick={() => onSelect(b.key)}
              title={b.note}
              style={{
                display: "flex",
                gap: 8,
                alignItems: "flex-start",
                textAlign: "left",
                // Amber, like the outline it draws on the regions it spans.
                background: selected ? "#fffbeb" : "#ffffff",
                border: selected ? "2px solid #d97706" : "1px solid #d1d5db",
                borderRadius: 8,
                padding: selected ? "6px 9px" : "7px 10px",
                cursor: "pointer",
                color: "#1f2937",
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  flex: "0 0 auto",
                  width: 18,
                  height: 18,
                  marginTop: 1,
                  borderRadius: 4,
                  background: fill,
                  boxSizing: "border-box",
                  border: inVitro.length ? `2px dashed ${IN_VITRO_STROKE}` : "1px solid #d1d5db",
                }}
              />
              <span>
                <span style={{ display: "block", fontSize: 13, fontWeight: 700 }}>{b.label}</span>
                <span style={{ display: "block", fontSize: 12, color: "#6b7280" }}>
                  {plural(tissue.length, "tissue dataset")}
                  {inVitro.length > 0 && ` · ${inVitro.length} in vitro`}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function NotRegionSpecific({
  region,
  datasets,
  selected,
  onSelect,
}: {
  region: RegionDef;
  datasets: Dataset[];
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <section
      aria-label="Not region-specific"
      data-bucket={region.key}
      style={{ ...card, background: "#f9fafb", borderStyle: "solid", borderColor: selected ? "#111827" : "#e5e7eb" }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <h2 style={{ fontSize: 14, fontWeight: 700, margin: 0 }}>
          {region.label} ({datasets.length})
        </h2>
        {datasets.length > 0 && (
          <button type="button" onClick={onSelect} aria-pressed={selected} style={linkButton}>
            details
          </button>
        )}
      </div>
      <p style={{ fontSize: 12, color: "#6b7280", margin: "2px 0 6px" }}>{region.note}</p>
      {datasets.length === 0 ? (
        <p style={{ fontSize: 13, color: "#6b7280", margin: 0 }}>None with the current selection.</p>
      ) : (
        <ul style={{ margin: 0, padding: 0, display: "flex", flexWrap: "wrap", gap: "2px 14px", fontSize: 13 }}>
          {datasets.map((d) => (
            <li key={d.table_name} style={{ listStyle: "none" }}>
              <Link href={datasetHref(d)} style={linkStyle}>
                {datasetTitle(d)}
              </Link>{" "}
              <span style={{ color: "#6b7280", fontSize: 12 }}>
                ({(d.anatomy ?? []).map((t) => t.label).join(", ")})
              </span>
              {datasetSource(d) === "in_vitro" && (
                <>
                  {" "}
                  <InVitroChip />
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SelectionPanel({
  region,
  view,
  specific,
  broader,
  assayLabel,
  matrixTables,
  genes,
  genesLoading,
  gene,
  onClose,
}: {
  region: RegionDef;
  view: BrainView;
  specific: Dataset[];
  broader: Dataset[];
  assayLabel: AssayLabeler;
  matrixTables: ReadonlySet<string>;
  genes: RegionGenesResponse | null;
  genesLoading: boolean;
  gene: GeneInPanel | null;
  onClose: () => void;
}) {
  const kinds = countBy(specific, (d) => studyKind(d)) as Array<[StudyKind, number]>;
  const fullHref = region.filterGroup ? fullDatasetsRegionHref(region.filterGroup) : null;
  const inMatrix = specific.filter((d) => matrixTables.has(d.table_name)).map((d) => d.table_name);
  const subtitle =
    region.kind === "drawn"
      ? BRAIN_VIEW_LABELS[view]
      : region.kind === "coarse"
        ? "Not counted in any single region"
        : "No brain region";

  return (
    <div data-panel={region.key}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{region.label}</h2>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
            {subtitle} · <UberonLink id={region.uberon} />
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close panel"
          style={{ border: "1px solid #d1d5db", background: "#fff", borderRadius: 6, cursor: "pointer", padding: "2px 8px" }}
        >
          ×
        </button>
      </div>
      {region.note && <p style={{ fontSize: 13, color: "#4b5563", margin: "8px 0 0" }}>{region.note}</p>}

      {(fullHref || specific.length > 0) && (
        <div data-panel-links style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 10, fontSize: 13 }}>
          {fullHref && (
            <Link href={fullHref} style={linkStyle} data-link="full-datasets">
              → All datasets in this region on the Full datasets page
              <span style={{ color: "#6b7280" }}> (incl. subregions; every source)</span>
            </Link>
          )}
          {specific.length > 0 &&
            (inMatrix.length > 0 ? (
              <Link href={matrixTablesHref(inMatrix)} style={linkStyle} data-link="matrix">
                → {inMatrix.length === 1 ? "This dataset" : `These ${inMatrix.length} datasets`} in the
                cross-modality matrix
              </Link>
            ) : (
              <span style={{ color: "#6b7280" }}>
                {genes && !genesLoading ? "None of these datasets is in the cross-modality matrix." : "Checking the matrix…"}
              </span>
            ))}
        </div>
      )}

      <PanelSection
        title={
          <>
            {plural(specific.length, "dataset")}
            {kinds.length > 0 && (
              <span style={{ marginLeft: 8, display: "inline-flex", gap: 4, flexWrap: "wrap", textTransform: "none", letterSpacing: 0 }}>
                {kinds.map(([k, n]) => (
                  <span key={k} style={{ display: "inline-flex", gap: 3, alignItems: "center", fontWeight: 400 }}>
                    <KindChip kind={k} /> {n}
                  </span>
                ))}
              </span>
            )}
          </>
        }
      >
        {specific.length === 0 ? (
          <p style={{ fontSize: 13, color: "#6b7280", margin: 0 }}>No datasets placed here with the current selection.</p>
        ) : (
          <DatasetGroups datasets={specific} assayLabel={assayLabel} matrixTables={matrixTables} gene={gene} />
        )}
      </PanelSection>

      {specific.length > 0 && !gene && (
        <PanelSection title="Perturbed genes and what changed">
          <PerturbedGenes datasets={specific} genes={genes} loading={genesLoading} />
        </PanelSection>
      )}

      {broader.length > 0 && (
        <PanelSection title={`+ ${plural(broader.length, "broader dataset")}`}>
          <p style={{ fontSize: 12, color: "#6b7280", margin: "0 0 6px" }}>
            Tagged with a larger region that contains this one (e.g. the whole cortex or brain), so not counted in its colour.
          </p>
          <details>
            <summary style={{ cursor: "pointer", fontSize: 13 }}>Show</summary>
            <DatasetGroups datasets={broader} assayLabel={assayLabel} matrixTables={matrixTables} gene={gene} />
            {!gene && <PerturbedGenes datasets={broader} genes={genes} loading={genesLoading} />}
          </details>
        </PanelSection>
      )}
    </div>
  );
}

function Intro({ datasets, view, geneMode }: { datasets: Dataset[]; view: BrainView; geneMode: boolean }) {
  const bySource = SOURCES.map((s) => [s.label, datasets.filter((d) => datasetSource(d) === s.key).length] as const);
  return (
    <div style={{ fontSize: 13, color: "#4b5563" }}>
      <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 6px", color: "#1f2937" }}>Pick a region</h2>
      <p style={{ margin: "0 0 6px" }}>
        {geneMode
          ? "Regions are coloured by the gene's datasets only; the label shows the count. Click a region for its datasets."
          : "Each label shows the region's dataset count. Click a region for its datasets, links to the Full datasets page and the matrix, and the perturbed genes with what changed."}
      </p>
      <p style={{ margin: "0 0 6px" }}>
        Human tissue data is postmortem, mostly case vs control; perturbations come from mouse and
        zebrafish in vivo and from in-vitro systems, which mostly name no lobe.
        {view === "human" && " Use the Mouse brain view to see them on mouse anatomy."}
      </p>
      <p style={{ margin: 0 }}>
        Shown: {bySource.map(([l, n]) => `${l} ${n}`).join(" · ")}
      </p>
      <p style={{ margin: "8px 0 0", fontSize: 12, color: "#6b7280" }}>
        Datasets without an anatomy tag (curated databases and gene lists) are not on this page.
      </p>
    </div>
  );
}
