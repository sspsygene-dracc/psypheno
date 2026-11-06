import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import type { Dataset } from "@/components/DatasetItem";
import BrainDrawing from "@/components/regions/BrainDrawing";
import { REGION_DRAWINGS, type RegionDrawing } from "@/lib/region-drawings";
import {
  DatasetGroups,
  KindChip,
  PanelSection,
  PerturbedGenes,
  UberonLink,
  type AssayLabeler,
} from "@/components/regions/RegionPanel";
import {
  COUNT_BINS,
  REGIONS,
  REGION_SPECIES,
  TRAY_GROUPS,
  countFill,
  countInk,
  findRegion,
  regionCounts,
  studyKind,
  trayCoversRegion,
  trayGroups,
  unplacedTissue,
  type RegionDef,
  type RegionSpecies,
  type StudyKind,
  type TrayGroup,
} from "@/lib/brain-regions";
import { SPECIES_LABELS, modelSystemLabel } from "@/lib/dataset-tags";
import type { RegionGenesResponse } from "@/pages/api/region-genes";
import type { Modality } from "@/pages/api/modalities";

/**
 * /regions — brain-region dataset navigator. One schematic drawing per
 * species, regions coloured by how many tissue datasets were sampled there;
 * click a region for its datasets and (for perturbation datasets) the
 * perturbed genes with their significant / measured readout counts. In-vitro
 * systems sit in a separate tray, grouped by the identity they were
 * patterned towards, so they never read as actual brain tissue.
 *
 * URL: ?species=human|mouse|zebrafish &view=lateral|medial &region=<key> (a
 * region key from lib/brain-regions.ts, its UBERON id, or invitro:<group>).
 * A gene-first view (?gene=SYMBOL: colour by where that gene's data come
 * from) is not built yet — see the note rendered when ?gene= is present and
 * regionCounts(), which takes the dataset list the gene view would filter.
 */

type Selection =
  | { kind: "region"; region: RegionDef }
  | { kind: "tray"; group: TrayGroup }
  | null;

const card: CSSProperties = {
  background: "#ffffff",
  border: "1px solid #e5e7eb",
  borderRadius: 10,
  padding: 16,
};

function parseSpecies(v: unknown): RegionSpecies {
  return typeof v === "string" && (REGION_SPECIES as readonly string[]).includes(v)
    ? (v as RegionSpecies)
    : "human";
}

function countBy<T>(items: T[], key: (t: T) => string): Array<[string, number]> {
  const m = new Map<string, number>();
  for (const it of items) m.set(key(it), (m.get(key(it)) ?? 0) + 1);
  return Array.from(m.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export default function RegionsPage() {
  const router = useRouter();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [assayTypes, setAssayTypes] = useState<Record<string, string>>({});
  const [modalities, setModalities] = useState<Modality[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<{ key: string; x: number; y: number } | null>(null);
  const [trayHover, setTrayHover] = useState<string | null>(null);
  const [genes, setGenes] = useState<RegionGenesResponse | null>(null);
  const [genesLoading, setGenesLoading] = useState(false);
  const drawingBox = useRef<HTMLDivElement | null>(null);

  const species = parseSpecies(router.query.species);
  const drawings: readonly RegionDrawing[] = REGION_DRAWINGS[species];
  const viewParam = typeof router.query.view === "string" ? router.query.view : null;
  const drawing = drawings.find((d) => d.key === viewParam) ?? drawings[0];
  const geneParam = typeof router.query.gene === "string" ? router.query.gene : null;

  const regionParam = typeof router.query.region === "string" ? router.query.region : null;
  const selection: Selection = useMemo(() => {
    if (!regionParam) return null;
    if (regionParam.startsWith("invitro:")) {
      const g = TRAY_GROUPS.find((t) => t.key === regionParam.slice("invitro:".length));
      return g ? { kind: "tray", group: g } : null;
    }
    const r =
      findRegion(species, regionParam) ??
      REGIONS[species].find((x) => x.uberon === regionParam && !x.pseudo);
    return r ? { kind: "region", region: r } : null;
  }, [regionParam, species]);

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

  const counts = useMemo(() => regionCounts(datasets, species), [datasets, species]);
  const tray = useMemo(() => trayGroups(datasets), [datasets]);
  const unplaced = useMemo(() => unplacedTissue(datasets, species), [datasets, species]);
  const wholeRegion = REGIONS[species].find((r) => r.pseudo);

  const setQuery = (patch: Record<string, string | null>) => {
    const q: Record<string, string> = {};
    for (const [k, v] of Object.entries({ ...router.query, ...patch })) {
      if (typeof v === "string" && v !== "") q[k] = v;
    }
    router.replace({ pathname: router.pathname, query: q }, undefined, { shallow: true, scroll: false });
  };

  const selectRegion = (key: string | null) => setQuery({ region: key });

  // Datasets the panel lists, and so the tables whose genes it needs.
  const panel = useMemo(() => {
    if (!selection) return null;
    if (selection.kind === "tray") {
      return { specific: tray.get(selection.group.key) ?? [], broader: [] as Dataset[] };
    }
    return counts.get(selection.region.key) ?? { specific: [], broader: [] };
  }, [selection, counts, tray]);

  const panelTables = useMemo(
    () =>
      panel
        ? Array.from(new Set([...panel.specific, ...panel.broader].map((d) => d.table_name))).sort()
        : [],
    [panel],
  );
  const panelTablesKey = panelTables.join(",");

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

  const outlinedKeys = useMemo(() => {
    const g = TRAY_GROUPS.find((t) => t.key === trayHover) ??
      (selection?.kind === "tray" ? selection.group : undefined);
    if (!g) return new Set<string>();
    return new Set(REGIONS[species].filter((r) => trayCoversRegion(g, r)).map((r) => r.key));
  }, [trayHover, selection, species]);

  const paint = (key: string) => {
    const n = counts.get(key)?.specific.length ?? 0;
    const label = findRegion(species, key)?.label ?? key;
    return { fill: countFill(n), ink: countInk(n), count: n, label };
  };

  const onHover = (key: string | null, e?: { clientX: number; clientY: number }) => {
    if (!key) return setHover(null);
    const box = drawingBox.current?.getBoundingClientRect();
    if (e && box) setHover({ key, x: e.clientX - box.left, y: e.clientY - box.top });
    else setHover((h) => (h && h.key === key ? h : { key, x: 20, y: 20 }));
  };

  const hovered = hover ? findRegion(species, hover.key) : undefined;
  const hoveredCounts = hover ? counts.get(hover.key) : undefined;

  return (
    <>
      <Head>
        <title>Brain regions &mdash; SSPsyGene</title>
      </Head>
      <Header />
      <main style={{ maxWidth: 1280, margin: "0 auto", padding: "24px 16px", color: "#1f2937" }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 6 }}>Brain regions</h1>
        <p style={{ fontSize: 14, color: "#4b5563", marginTop: 0, maxWidth: 900 }}>
          Where the datasets come from. Each drawing colours a region by the number of tissue
          datasets sampled there; click a region to list them and, for perturbation datasets, the
          perturbed genes with how many readouts changed. Stem-cell models are in the in-vitro tray:
          their region is the identity they were patterned towards, not tissue.
        </p>

        {geneParam && (
          <div
            role="note"
            style={{ ...card, background: "#fffbeb", borderColor: "#fde68a", padding: 10, marginBottom: 12, fontSize: 13 }}
          >
            The gene view (where <strong>{geneParam}</strong>&rsquo;s data come from) is not available
            yet; showing all datasets. Search the gene on the <Link href={`/?perturbed=${encodeURIComponent(geneParam)}`}>home page</Link> instead.
          </div>
        )}

        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
          <div role="tablist" aria-label="Species" style={{ display: "inline-flex", gap: 4 }}>
            {REGION_SPECIES.map((s) => (
              <button
                key={s}
                role="tab"
                type="button"
                aria-selected={s === species}
                onClick={() => setQuery({ species: s, view: null, region: null })}
                style={toggleStyle(s === species)}
              >
                {SPECIES_LABELS[s] ?? s}
              </button>
            ))}
          </div>
          {drawings.length > 1 && (
            <div role="group" aria-label="View" style={{ display: "inline-flex", gap: 4, marginLeft: 12 }}>
              {drawings.map((d) => (
                <button
                  key={d.key}
                  type="button"
                  aria-pressed={d.key === drawing.key}
                  onClick={() => setQuery({ view: d.key })}
                  style={toggleStyle(d.key === drawing.key)}
                >
                  {d.label}
                </button>
              ))}
            </div>
          )}
        </div>

        {error && <p style={{ color: "#b91c1c" }}>{error}</p>}

        <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 560px", minWidth: 320 }}>
            <div style={card}>
              <div ref={drawingBox} style={{ position: "relative" }}>
                <BrainDrawing
                  drawing={drawing}
                  paint={paint}
                  selectedKey={selection?.kind === "region" ? selection.region.key : null}
                  outlinedKeys={outlinedKeys}
                  onHover={onHover}
                  onSelect={(k) => selectRegion(k)}
                />
                {hover && hovered && (
                  <HoverCard
                    x={hover.x}
                    y={hover.y}
                    region={hovered}
                    specific={hoveredCounts?.specific ?? []}
                    broader={hoveredCounts?.broader ?? []}
                    assayLabel={assayLabel}
                  />
                )}
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
              {wholeRegion && (
                <div style={{ marginTop: 10, fontSize: 13 }}>
                  <button
                    type="button"
                    onClick={() => selectRegion(wholeRegion.key)}
                    aria-pressed={selection?.kind === "region" && selection.region.key === wholeRegion.key}
                    style={toggleStyle(selection?.kind === "region" && selection.region.key === wholeRegion.key)}
                  >
                    {wholeRegion.label}: {counts.get(wholeRegion.key)?.specific.length ?? 0} dataset
                    {(counts.get(wholeRegion.key)?.specific.length ?? 0) === 1 ? "" : "s"}
                  </button>
                  <span style={{ color: "#6b7280", marginLeft: 8 }}>
                    not drawn as a region, so they don&rsquo;t colour every area
                  </span>
                </div>
              )}
              {unplaced.length > 0 && (
                <p style={{ fontSize: 12, color: "#6b7280", margin: "8px 0 0" }}>
                  Not placed on this drawing: {unplaced.map((d) => d.medium_label ?? d.table_name).join(", ")}
                </p>
              )}
            </div>
          </div>

          <div style={{ flex: "1 1 420px", minWidth: 320, display: "flex", flexDirection: "column", gap: 16 }}>
            <InVitroTray
              tray={tray}
              selectedKey={selection?.kind === "tray" ? selection.group.key : null}
              onHover={setTrayHover}
              onSelect={(k) => selectRegion(`invitro:${k}`)}
              loading={loading}
            />
            <div style={card} aria-live="polite">
              {loading ? (
                <p style={{ margin: 0, color: "#6b7280" }}>Loading datasets…</p>
              ) : selection && panel ? (
                <SelectionPanel
                  selection={selection}
                  species={species}
                  specific={panel.specific}
                  broader={panel.broader}
                  tray={tray}
                  assayLabel={assayLabel}
                  matrixTables={matrixTables}
                  genes={genes}
                  genesLoading={genesLoading}
                  onSelectTray={(k) => selectRegion(`invitro:${k}`)}
                  onClose={() => selectRegion(null)}
                />
              ) : (
                <Intro datasets={datasets} />
              )}
            </div>
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}

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

function Legend() {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#4b5563" }}>
      Datasets:
      {COUNT_BINS.map((b) => (
        <span key={b.label} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
          <span
            aria-hidden="true"
            style={{ width: 14, height: 14, borderRadius: 3, background: b.fill, border: "1px solid #d1d5db" }}
          />
          {b.label}
        </span>
      ))}
      <span style={{ display: "inline-flex", alignItems: "center", gap: 3, marginLeft: 6 }}>
        <span
          aria-hidden="true"
          style={{ width: 14, height: 14, borderRadius: 3, border: "2px dashed #7c3aed" }}
        />
        in-vitro identity
      </span>
    </span>
  );
}

function HoverCard({
  x,
  y,
  region,
  specific,
  broader,
  assayLabel,
}: {
  x: number;
  y: number;
  region: RegionDef;
  specific: Dataset[];
  broader: Dataset[];
  assayLabel: AssayLabeler;
}) {
  const bySystem = countBy(specific, (d) => modelSystemLabel(d.model_system ?? ""));
  const byAssay = countBy(specific, assayLabel);
  return (
    <div
      role="tooltip"
      style={{
        position: "absolute",
        left: Math.min(x + 14, 9999),
        top: y + 14,
        pointerEvents: "none",
        background: "#111827",
        color: "#f9fafb",
        borderRadius: 8,
        padding: "8px 10px",
        fontSize: 12,
        lineHeight: 1.5,
        maxWidth: 280,
        boxShadow: "0 4px 12px rgba(0,0,0,.2)",
        zIndex: 5,
      }}
    >
      <div style={{ fontWeight: 700, fontSize: 13 }}>{region.label}</div>
      <div>
        {specific.length} dataset{specific.length === 1 ? "" : "s"}
        {bySystem.length > 0 && `: ${bySystem.map(([k, n]) => `${n} ${k.toLowerCase()}`).join(", ")}`}
      </div>
      {byAssay.length > 0 && (
        <div style={{ color: "#d1d5db" }}>{byAssay.map(([k, n]) => `${n} ${k}`).join(" · ")}</div>
      )}
      {broader.length > 0 && (
        <div style={{ color: "#d1d5db" }}>
          + {broader.length} broader (e.g. whole brain)
        </div>
      )}
      <div style={{ color: "#9ca3af", marginTop: 2 }}>Click for details</div>
    </div>
  );
}

function InVitroTray({
  tray,
  selectedKey,
  onHover,
  onSelect,
  loading,
}: {
  tray: Map<string, Dataset[]>;
  selectedKey: string | null;
  onHover: (key: string | null) => void;
  onSelect: (key: string) => void;
  loading: boolean;
}) {
  return (
    <section
      aria-label="In-vitro tray"
      style={{ ...card, background: "#faf9ff", border: "1px dashed #a78bfa" }}
    >
      <h2 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 2px" }}>In-vitro tray</h2>
      <p style={{ fontSize: 12, color: "#6b7280", margin: "0 0 10px" }}>
        Organoids, iPSC-derived neurons, primary cultures and cell lines, grouped by intended
        identity — what they were patterned towards, not a brain region they were taken from.
        Hover to outline the matching regions.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8 }}>
        {TRAY_GROUPS.map((g) => {
          const items = tray.get(g.key) ?? [];
          const systems = countBy(items, (d) => modelSystemLabel(d.model_system ?? ""));
          const selected = selectedKey === g.key;
          return (
            <button
              key={g.key}
              type="button"
              data-tray={g.key}
              aria-pressed={selected}
              disabled={!loading && items.length === 0}
              onMouseEnter={() => onHover(g.key)}
              onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(g.key)}
              onBlur={() => onHover(null)}
              onClick={() => onSelect(g.key)}
              title={g.description}
              style={{
                textAlign: "left",
                background: selected ? "#ede9fe" : "#ffffff",
                border: `1.5px dashed ${selected ? "#7c3aed" : "#c4b5fd"}`,
                borderRadius: 8,
                padding: "8px 10px",
                cursor: items.length ? "pointer" : "default",
                opacity: items.length || loading ? 1 : 0.55,
                color: "#1f2937",
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 700 }}>
                {g.label} <span style={{ fontWeight: 400, color: "#6b7280" }}>({items.length})</span>
              </div>
              <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
                {systems.length > 0 ? systems.map(([k, n]) => `${n} ${k}`).join(" · ") : g.description}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function SelectionPanel({
  selection,
  species,
  specific,
  broader,
  tray,
  assayLabel,
  matrixTables,
  genes,
  genesLoading,
  onSelectTray,
  onClose,
}: {
  selection: NonNullable<Selection>;
  species: RegionSpecies;
  specific: Dataset[];
  broader: Dataset[];
  tray: Map<string, Dataset[]>;
  assayLabel: AssayLabeler;
  matrixTables: ReadonlySet<string>;
  genes: RegionGenesResponse | null;
  genesLoading: boolean;
  onSelectTray: (key: string) => void;
  onClose: () => void;
}) {
  const isTray = selection.kind === "tray";
  const title = isTray ? selection.group.label : selection.region.label;
  const region = isTray ? null : selection.region;
  const kinds = countBy(specific, (d) => studyKind(d)) as Array<[StudyKind, number]>;
  const covering = region
    ? TRAY_GROUPS.filter((g) => trayCoversRegion(g, region) && (tray.get(g.key)?.length ?? 0) > 0)
    : [];
  // A "show all in /full-datasets" link (?region=<REGION_GROUPS id>) belongs
  // here once /full-datasets reads ?region= from the URL.

  return (
    <div data-panel={isTray ? `invitro:${selection.group.key}` : selection.region.key}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{title}</h2>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
            {isTray ? (
              <>In vitro · intended identity, not measured anatomy</>
            ) : (
              <>
                {SPECIES_LABELS[species]} · <UberonLink id={selection.region.uberon} />
              </>
            )}
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
      {(isTray ? selection.group.description : region?.note) && (
        <p style={{ fontSize: 13, color: "#4b5563", margin: "8px 0 0" }}>
          {isTray ? selection.group.description : region?.note}
        </p>
      )}

      <PanelSection
        title={
          <>
            {specific.length} dataset{specific.length === 1 ? "" : "s"}
            {kinds.length > 0 && (
              <span style={{ marginLeft: 8, display: "inline-flex", gap: 4, textTransform: "none", letterSpacing: 0 }}>
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
          <p style={{ fontSize: 13, color: "#6b7280", margin: 0 }}>
            No {isTray ? "" : "tissue "}datasets tagged here yet.
          </p>
        ) : (
          <DatasetGroups datasets={specific} assayLabel={assayLabel} matrixTables={matrixTables} />
        )}
      </PanelSection>

      {specific.length > 0 && (
        <PanelSection title="Perturbed genes and what changed">
          <PerturbedGenes datasets={specific} genes={genes} loading={genesLoading} />
        </PanelSection>
      )}

      {broader.length > 0 && (
        <PanelSection title={`+ ${broader.length} broader dataset${broader.length === 1 ? "" : "s"}`}>
          <p style={{ fontSize: 12, color: "#6b7280", margin: "0 0 6px" }}>
            Sampled from a larger region that contains this one (e.g. whole brain), so not counted in the colour.
          </p>
          <details>
            <summary style={{ cursor: "pointer", fontSize: 13 }}>Show</summary>
            <DatasetGroups datasets={broader} assayLabel={assayLabel} matrixTables={matrixTables} />
            <PerturbedGenes datasets={broader} genes={genes} loading={genesLoading} />
          </details>
        </PanelSection>
      )}

      {covering.length > 0 && (
        <PanelSection title="Modelled in vitro">
          <p style={{ fontSize: 12, color: "#6b7280", margin: "0 0 6px" }}>
            Stem-cell models patterned towards this region (intended identity).
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {covering.map((g) => (
              <button
                key={g.key}
                type="button"
                onClick={() => onSelectTray(g.key)}
                style={{
                  fontSize: 12,
                  border: "1.5px dashed #a78bfa",
                  background: "#faf9ff",
                  borderRadius: 6,
                  padding: "3px 8px",
                  cursor: "pointer",
                }}
              >
                {g.label} ({tray.get(g.key)?.length ?? 0})
              </button>
            ))}
          </div>
        </PanelSection>
      )}

    </div>
  );
}

function Intro({ datasets }: { datasets: Dataset[] }) {
  const lines = REGION_SPECIES.map((s) => {
    const c = regionCounts(datasets, s);
    const n = new Set(Array.from(c.values()).flatMap((v) => [...v.specific, ...v.broader].map((d) => d.table_name))).size;
    return `${SPECIES_LABELS[s]}: ${n} tissue dataset${n === 1 ? "" : "s"}`;
  });
  return (
    <div style={{ fontSize: 13, color: "#4b5563" }}>
      <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 6px", color: "#1f2937" }}>Pick a region</h2>
      <p style={{ margin: "0 0 6px" }}>
        Hover a region for its dataset count; click it for the datasets and perturbed genes.
      </p>
      <p style={{ margin: "0 0 6px" }}>
        Human tissue data is postmortem case-vs-control; perturbations come from mouse and
        zebrafish in vivo and from the in-vitro systems.
      </p>
      <p style={{ margin: 0 }}>{lines.join(" · ")}</p>
      <p style={{ margin: "8px 0 0", fontSize: 12, color: "#6b7280" }}>
        Datasets without an anatomy tag (e.g. curated databases and gene lists) are not shown.
      </p>
    </div>
  );
}
