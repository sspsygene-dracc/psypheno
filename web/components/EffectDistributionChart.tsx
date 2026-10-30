import { useEffect, useMemo, useState, type MouseEvent } from "react";
import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  XAxis,
  YAxis,
} from "recharts";

type GeneRow = {
  effect: number | null;
  pvalue: number | null;
  fdr: number | null;
  rowKey: string;
  effectCapped?: boolean;
};

type VolcanoPoint = {
  effect: number;
  negLog10P: number;
  fdr: number | null;
  topByP: boolean;
  symbol: string | null;
  // Stored effect is ±Inf; `effect` is where it is drawn.
  effectCapped?: boolean;
};

// A clicked dot: a background point, or a queried-gene row (which has rowKey).
type SelectedDot = VolcanoPoint & {
  dotId: string;
  pvalue?: number | null;
  rowKey?: string;
};

// The dots stacked under one click spot, closest first.
type DotCycle = { x: number; y: number; dotIds: string[]; index: number };

type DotShapeProps = {
  cx?: number;
  cy?: number;
  fill?: string;
  fillOpacity?: number;
  stroke?: string;
  strokeWidth?: number;
  payload?: { dotId?: string };
};

function VolcanoDot({
  cx,
  cy,
  fill,
  fillOpacity,
  stroke,
  strokeWidth,
  payload,
}: DotShapeProps) {
  return (
    <g style={{ cursor: "pointer" }}>
      <circle
        cx={cx}
        cy={cy}
        r={DOT_HIT_RADIUS}
        fill="transparent"
        data-dot-id={payload?.dotId}
      />
      <circle
        cx={cx}
        cy={cy}
        r={DOT_RADIUS}
        fill={fill}
        fillOpacity={fillOpacity}
        stroke={stroke}
        strokeWidth={strokeWidth}
      />
    </g>
  );
}

function SelectedRing({ cx, cy }: DotShapeProps) {
  return (
    <circle
      cx={cx}
      cy={cy}
      r={DOT_RADIUS + 2.5}
      fill="none"
      stroke={COLOR_GENE_OUTLINE}
      strokeWidth={1.5}
      style={{ pointerEvents: "none" }}
    />
  );
}

type DistributionResponse = {
  effectColumn: string;
  pvalueColumn: string;
  fdrColumn: string | null;
  nTotal: number;
  nNonNull: number;
  // Which home-page query param a tooltip's gene link should use, or null
  // when the table has no single labelling link table (#189).
  labelDirection: "target" | "perturbed" | null;
  // One row per gene: the background stays whole-table and a searched
  // perturbed gene is the orange dot.
  perGeneTable?: boolean;
  volcanoPoints: VolcanoPoint[];
  geneRows: GeneRow[];
  fieldLabels?: Record<string, string>;
};

const SIG_THRESHOLD = 0.05;
const VOLCANO_SAMPLE_CAP = 1000;
const BACKGROUND_OPACITY = 0.35;

const COLOR_UP = "#dc2626"; // red
const COLOR_DOWN = "#2563eb"; // blue
const COLOR_NS = "#cbd5e1"; // light grey
const COLOR_GENE = "#f59e0b"; // amber for queried gene
const COLOR_GENE_OUTLINE = "#111827";
const DOT_RADIUS = 4.5;
// Slightly larger than the dot, so clicks needn't be exact.
const DOT_HIT_RADIUS = 6;
// A click this close to the previous one steps through the dots there.
const CYCLE_TOLERANCE_PX = 5;

type Category = "up" | "down" | "ns";

function classify(effect: number, fdr: number | null, p: number | null): Category {
  // Per Max (2026-04-28): use FDR ≤ 0.05; fall back to p-value when no FDR.
  const sig = fdr != null ? fdr <= SIG_THRESHOLD : p != null && p <= SIG_THRESHOLD;
  if (!sig) return "ns";
  return effect > 0 ? "up" : "down";
}

function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1000 || (Math.abs(n) > 0 && Math.abs(n) < 0.01)) {
    return n.toExponential(digits);
  }
  return n.toPrecision(digits + 1);
}

export default function EffectDistributionChart({
  tableName,
  perturbedCentralGeneId,
  targetCentralGeneId,
  geneSymbol,
  perturbedGeneSymbol,
}: {
  tableName: string;
  perturbedCentralGeneId?: number;
  targetCentralGeneId?: number;
  geneSymbol?: string;
  perturbedGeneSymbol?: string;
}) {
  const [data, setData] = useState<DistributionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<SelectedDot | null>(null);
  const [cycle, setCycle] = useState<DotCycle | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelected(null);
    setCycle(null);
    fetch("/api/effect-distribution", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tableName,
        perturbedCentralGeneId,
        targetCentralGeneId,
      }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: DistributionResponse) => {
        if (!cancelled) {
          setData(d);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(String(e));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tableName, perturbedCentralGeneId, targetCentralGeneId]);

  // Hooks must run unconditionally; compute on whatever data we have, even
  // when null, and gate the render below.
  const seriesByCategory = useMemo(() => {
    const byCat: Record<Category, SelectedDot[]> = { up: [], down: [], ns: [] };
    if (!data) return byCat;
    for (const [i, p] of data.volcanoPoints.entries()) {
      // Undo the -log10 for tables with no FDR; the rounding keeps a p of
      // exactly 0.05 on the significant side of the threshold.
      const pvalue = Number(Math.pow(10, -p.negLog10P).toPrecision(12));
      const cat = classify(p.effect, p.fdr, pvalue);
      byCat[cat].push({ ...p, dotId: `bg-${i}` });
    }
    return byCat;
  }, [data]);

  const geneScatter = useMemo(() => {
    if (!data) return [];
    return data.geneRows
      .filter(
        (r) =>
          r.effect != null &&
          r.pvalue != null &&
          Number.isFinite(r.effect) &&
          Number.isFinite(r.pvalue),
      )
      .map((r) => ({
        effect: r.effect as number,
        negLog10P: -Math.log10(Math.max(r.pvalue as number, 1e-300)),
        pvalue: r.pvalue,
        fdr: r.fdr,
        rowKey: r.rowKey,
        effectCapped: r.effectCapped,
        dotId: `gene-${r.rowKey}`,
      }));
  }, [data]);

  if (loading) {
    return (
      <div style={{ padding: 12, fontSize: 13, color: "#6b7280" }}>
        Loading volcano…
      </div>
    );
  }
  if (error || !data) {
    return (
      <div style={{ padding: 12, fontSize: 13, color: "#dc2626" }}>
        Could not load volcano{error ? `: ${error}` : "."}
      </div>
    );
  }

  const sigLabel = data.fdrColumn
    ? `${data.fdrColumn} ≤ ${SIG_THRESHOLD}`
    : `${data.pvalueColumn} ≤ ${SIG_THRESHOLD}`;

  const upCount = seriesByCategory.up.length;
  const downCount = seriesByCategory.down.length;
  const nsCount = seriesByCategory.ns.length;

  const labels = data.fieldLabels ?? {};
  const labelFor = (col: string | null | undefined): string | null => {
    if (!col) return null;
    return labels[col.toLowerCase()] ?? null;
  };
  const effectLabel = labelFor(data.effectColumn);
  const pvalueLabel = labelFor(data.pvalueColumn);
  const fdrLabel = labelFor(data.fdrColumn);

  const highlightSymbol = data.perGeneTable
    ? (perturbedGeneSymbol ?? geneSymbol)
    : geneSymbol;

  const hasCappedEffects =
    data.volcanoPoints.some((p) => p.effectCapped) ||
    data.geneRows.some((r) => r.effectCapped);
  const cappedNote = `Rows with an infinite ${data.effectColumn} are drawn at the largest finite value in this table.`;

  const dotById = new Map<string, SelectedDot>();
  for (const dot of [
    ...Object.values(seriesByCategory).flat(),
    ...(geneScatter as unknown as SelectedDot[]),
  ]) {
    dotById.set(dot.dotId, dot);
  }

  const clearSelection = () => {
    setSelected(null);
    setCycle(null);
  };

  const handlePlotClick = (e: MouseEvent<HTMLDivElement>) => {
    const { clientX: x, clientY: y } = e;
    if (
      cycle &&
      selected &&
      Math.hypot(x - cycle.x, y - cycle.y) <= CYCLE_TOLERANCE_PX
    ) {
      if (cycle.dotIds.length === 1) {
        clearSelection();
        return;
      }
      const index = (cycle.index + 1) % cycle.dotIds.length;
      setCycle({ ...cycle, index });
      setSelected(dotById.get(cycle.dotIds[index]) ?? null);
      return;
    }
    // Every dot under the pointer; the queried gene first, then closest.
    const hits = document
      .elementsFromPoint(x, y)
      .filter((el) => el.hasAttribute("data-dot-id"))
      .map((el) => {
        const box = el.getBoundingClientRect();
        const distance = Math.hypot(
          x - (box.left + box.width / 2),
          y - (box.top + box.height / 2),
        );
        const dotId = el.getAttribute("data-dot-id") as string;
        return { dotId, distance, isGene: dotId.startsWith("gene-") };
      })
      .sort(
        (a, b) =>
          Number(b.isGene) - Number(a.isGene) || a.distance - b.distance,
      );
    if (hits.length === 0) return;
    setCycle({ x, y, dotIds: hits.map((h) => h.dotId), index: 0 });
    setSelected(dotById.get(hits[0].dotId) ?? null);
  };

  // Orange (queried-gene) dots carry the searched gene: the perturbed one on
  // per-gene tables, otherwise the target. Background dots use whatever
  // direction the table labels by (#189).
  const selectedIsGene = selected?.rowKey != null;
  const selectedSymbol = selectedIsGene
    ? (highlightSymbol ?? null)
    : (selected?.symbol ?? null);
  const selectedDirection = !selectedIsGene
    ? data.labelDirection
    : data.perGeneTable
      ? "perturbed"
      : "target";
  const selectedHref =
    selectedSymbol && selectedDirection
      ? `/?${selectedDirection}=${encodeURIComponent(selectedSymbol)}`
      : null;

  const explainer = [
    `Each background dot is one row from the table; click a dot to see its gene and values.`,
    `The sample is the top rows by p-value plus a deterministic pseudo-random sample (~${VOLCANO_SAMPLE_CAP.toLocaleString()} dots total); control-perturbed rows are excluded by default.`,
    `Red = significantly up, blue = significantly down, grey = not significant (${sigLabel}).`,
    `Orange dot${geneScatter.length === 1 ? "" : "s"} = ${highlightSymbol ?? "the queried gene"}'s row${geneScatter.length === 1 ? "" : "s"} in this table (full opacity).`,
    ...(hasCappedEffects ? [cappedNote] : []),
  ].join(" ");

  return (
    <div style={{ padding: "8px 0" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          flexWrap: "wrap",
          gap: 8,
          marginBottom: 4,
          fontSize: 12,
          color: "#6b7280",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span>
            {data.effectColumn} vs −log<sub>10</sub>({data.pvalueColumn}) · n ={" "}
            {data.nNonNull.toLocaleString()} · sig: {sigLabel}
          </span>
          <span
            title={explainer}
            aria-label="What do the colors mean?"
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 14,
              height: 14,
              borderRadius: 9999,
              border: "1px solid #9ca3af",
              color: "#6b7280",
              fontSize: 10,
              fontStyle: "italic",
              fontFamily: "Georgia, serif",
              cursor: "help",
              lineHeight: 1,
              userSelect: "none",
            }}
          >
            i
          </span>
        </div>
        <div style={{ display: "flex", gap: 12 }}>
          <LegendDot
            color={COLOR_DOWN}
            opacity={BACKGROUND_OPACITY}
            label={`Down (${downCount})`}
          />
          <LegendDot
            color={COLOR_NS}
            opacity={BACKGROUND_OPACITY}
            label={`Not sig. (${nsCount})`}
          />
          <LegendDot
            color={COLOR_UP}
            opacity={BACKGROUND_OPACITY}
            label={`Up (${upCount})`}
          />
          {geneScatter.length > 0 && (
            <LegendDot
              color={COLOR_GENE}
              outline={COLOR_GENE_OUTLINE}
              label={`${geneSymbol ?? "gene"} (${geneScatter.length})`}
            />
          )}
        </div>
      </div>

      {data.perGeneTable &&
        perturbedCentralGeneId != null &&
        perturbedCentralGeneId > 0 &&
        geneScatter.length === 0 && (
          <div style={{ marginBottom: 4, fontSize: 12, color: "#6b7280" }}>
            {`${highlightSymbol ?? "This gene"} has no plottable ` +
              `${data.effectColumn} / ${data.pvalueColumn} values in this ` +
              `table, so it isn't highlighted.`}
          </div>
        )}
      {/* Don't let a click focus the chart: it draws a box around the plot. */}
      <div onMouseDown={(e) => e.preventDefault()} onClick={handlePlotClick}>
      <ResponsiveContainer width="100%" height={280}>
        <ScatterChart margin={{ top: 6, right: 16, bottom: 28, left: 8 }}>
          <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="effect"
            tick={{ fontSize: 11 }}
            label={{
              value: data.effectColumn,
              position: "insideBottom",
              offset: -10,
              fontSize: 12,
            }}
          />
          <YAxis
            type="number"
            dataKey="negLog10P"
            tick={{ fontSize: 11 }}
            label={{
              value: `-log10(${data.pvalueColumn})`,
              angle: -90,
              position: "insideLeft",
              fontSize: 12,
            }}
          />
          <ReferenceLine x={0} stroke="#9ca3af" strokeDasharray="4 4" />
          <Scatter
            name="ns"
            data={seriesByCategory.ns}
            fill={COLOR_NS}
            fillOpacity={BACKGROUND_OPACITY}
            isAnimationActive={false}
            shape={VolcanoDot}
          />
          <Scatter
            name="down"
            data={seriesByCategory.down}
            fill={COLOR_DOWN}
            fillOpacity={BACKGROUND_OPACITY}
            isAnimationActive={false}
            shape={VolcanoDot}
          />
          <Scatter
            name="up"
            data={seriesByCategory.up}
            fill={COLOR_UP}
            fillOpacity={BACKGROUND_OPACITY}
            isAnimationActive={false}
            shape={VolcanoDot}
          />
          {geneScatter.length > 0 && (
            <Scatter
              name="gene"
              data={geneScatter}
              fill={COLOR_GENE}
              stroke={COLOR_GENE_OUTLINE}
              strokeWidth={1.5}
              isAnimationActive={false}
              shape={VolcanoDot}
              legendType="circle"
            />
          )}
          {selected && (
            <Scatter
              name="selected"
              data={[selected]}
              isAnimationActive={false}
              shape={SelectedRing}
            />
          )}
        </ScatterChart>
      </ResponsiveContainer>
      </div>
      {selected ? (
        <div
          style={{
            position: "relative",
            marginTop: 4,
            padding: "8px 28px 8px 10px",
            border: "1px solid #d1d5db",
            borderRadius: 6,
            fontSize: 12,
          }}
        >
          <button
            type="button"
            aria-label="Close dot details"
            onClick={clearSelection}
            style={{
              position: "absolute",
              top: 4,
              right: 6,
              border: "none",
              background: "none",
              color: "#6b7280",
              cursor: "pointer",
              fontSize: 14,
            }}
          >
            ×
          </button>
          {cycle && cycle.dotIds.length > 1 && (
            <div style={{ color: "#6b7280", marginBottom: 2 }}>
              {`Dot ${cycle.index + 1} of ${cycle.dotIds.length} at this spot. Click again for the next.`}
            </div>
          )}
          {selectedSymbol && (
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              {selectedHref ? (
                <a
                  href={selectedHref}
                  style={{ color: "#1d4ed8", textDecoration: "none" }}
                >
                  {selectedSymbol}
                </a>
              ) : (
                selectedSymbol
              )}
            </div>
          )}
          <DetailRow
            label={effectLabel}
            column={data.effectColumn}
            value={
              selected.effectCapped
                ? `${selected.effect < 0 ? "−" : ""}∞ (drawn at ${fmt(selected.effect, 3)})`
                : fmt(selected.effect, 3)
            }
          />
          <DetailRow
            label={pvalueLabel}
            column={data.pvalueColumn}
            value={fmt(
              selected.pvalue ?? Math.pow(10, -selected.negLog10P),
              2,
            )}
          />
          {data.fdrColumn && (
            <DetailRow
              label={fdrLabel}
              column={data.fdrColumn}
              value={fmt(selected.fdr, 2)}
            />
          )}
        </div>
      ) : (
        <div style={{ marginTop: 4, fontSize: 12, color: "#6b7280" }}>
          Click a dot to see its gene and values.
        </div>
      )}
      {hasCappedEffects && (
        <div style={{ marginTop: 4, fontSize: 12, color: "#6b7280" }}>
          {cappedNote}
        </div>
      )}
    </div>
  );
}

function DetailRow({
  label,
  column,
  value,
}: {
  label: string | null;
  column: string;
  value: string;
}) {
  return (
    <div style={{ marginTop: 1 }}>
      <span>{label ?? column}: </span>
      <strong>{value}</strong>
      {label && (
        <span
          style={{
            marginLeft: 4,
            color: "#9ca3af",
            fontFamily:
              "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
            fontSize: 10.5,
          }}
        >
          [{column}]
        </span>
      )}
    </div>
  );
}

function LegendDot({
  color,
  outline,
  opacity,
  label,
}: {
  color: string;
  outline?: string;
  opacity?: number;
  label: string;
}) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span
        style={{
          display: "inline-block",
          width: 10,
          height: 10,
          background: color,
          opacity: opacity ?? 1,
          border: outline ? `1.5px solid ${outline}` : "none",
          borderRadius: 9999,
        }}
      />
      {label}
    </span>
  );
}
