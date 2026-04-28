import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

type GeneRow = {
  effect: number | null;
  pvalue: number | null;
  rowKey: string;
};

type DistributionResponse = {
  effectColumn: string;
  pvalueColumn: string;
  nTotal: number;
  nNonNull: number;
  histogram: { binEdges: number[]; binCounts: number[] };
  volcanoPoints: Array<{ effect: number; negLog10P: number; topByP: boolean }>;
  geneRows: GeneRow[];
};

const POSITIVE = "#2563eb";
const NEGATIVE = "#ef4444";
const MARKER = "#f59e0b";
const BACKGROUND_DOT = "#cbd5e1";

function fmt(n: number, digits = 2): string {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1000 || (Math.abs(n) > 0 && Math.abs(n) < 0.01)) {
    return n.toExponential(digits);
  }
  return n.toFixed(digits);
}

export default function EffectDistributionChart({
  tableName,
  centralGeneId,
  perturbedCentralGeneId,
  targetCentralGeneId,
  direction,
  geneSymbol,
}: {
  tableName: string;
  centralGeneId?: number;
  perturbedCentralGeneId?: number;
  targetCentralGeneId?: number;
  direction?: "target" | "perturbed";
  geneSymbol?: string;
}) {
  const [data, setData] = useState<DistributionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"histogram" | "volcano">("histogram");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch("/api/effect-distribution", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tableName,
        centralGeneId,
        perturbedCentralGeneId,
        targetCentralGeneId,
        direction,
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
  }, [
    tableName,
    centralGeneId,
    perturbedCentralGeneId,
    targetCentralGeneId,
    direction,
  ]);

  if (loading) {
    return (
      <div style={{ padding: 12, fontSize: 13, color: "#6b7280" }}>
        Loading distribution…
      </div>
    );
  }
  if (error || !data) {
    return (
      <div style={{ padding: 12, fontSize: 13, color: "#dc2626" }}>
        Could not load distribution{error ? `: ${error}` : "."}
      </div>
    );
  }

  const histBars = data.histogram.binCounts.map((count, i) => {
    const lo = data.histogram.binEdges[i];
    const hi = data.histogram.binEdges[i + 1];
    const mid = (lo + hi) / 2;
    return {
      mid,
      count,
      label: `${fmt(lo)} – ${fmt(hi)}`,
      sign: mid >= 0 ? "pos" : "neg",
    };
  });

  const geneEffects = data.geneRows
    .map((r) => r.effect)
    .filter((v): v is number => v != null && Number.isFinite(v));
  const geneScatter = data.geneRows
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
    }));

  const tabBtn = (
    label: string,
    key: "histogram" | "volcano",
    active: boolean,
  ) => (
    <button
      key={key}
      type="button"
      onClick={() => setTab(key)}
      style={{
        padding: "4px 12px",
        fontSize: 12,
        fontWeight: 600,
        background: active ? "#2563eb" : "#fff",
        color: active ? "#fff" : "#1e40af",
        border: "1px solid #2563eb",
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );

  return (
    <div style={{ padding: "8px 0" }}>
      <div
        style={{
          display: "flex",
          gap: 0,
          marginBottom: 8,
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex" }}>
          {tabBtn("Histogram", "histogram", tab === "histogram")}
          {tabBtn("Volcano", "volcano", tab === "volcano")}
        </div>
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          {data.effectColumn} vs {data.pvalueColumn} · n = {data.nNonNull}
          {geneSymbol && geneEffects.length > 0
            ? ` · ${geneSymbol}: ${geneEffects.map((v) => fmt(v)).join(", ")}`
            : ""}
        </div>
      </div>

      {tab === "histogram" && (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart
            data={histBars}
            margin={{ top: 6, right: 12, bottom: 24, left: 0 }}
          >
            <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
            <XAxis
              dataKey="mid"
              type="number"
              domain={[
                data.histogram.binEdges[0],
                data.histogram.binEdges[data.histogram.binEdges.length - 1],
              ]}
              tick={{ fontSize: 11 }}
              label={{
                value: data.effectColumn,
                position: "insideBottom",
                offset: -8,
                fontSize: 12,
              }}
            />
            <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
            <Tooltip
              formatter={(v) => [String(v), "count"]}
              labelFormatter={(_, payload) => {
                const p = payload?.[0]?.payload as
                  | { label: string }
                  | undefined;
                return p?.label ?? "";
              }}
            />
            <Bar dataKey="count" isAnimationActive={false}>
              {histBars.map((b, i) => (
                <Bar
                  key={`b-${i}`}
                  dataKey="count"
                  fill={b.sign === "pos" ? POSITIVE : NEGATIVE}
                />
              ))}
            </Bar>
            {geneEffects.map((e, i) => (
              <ReferenceLine
                key={`marker-${i}`}
                x={e}
                stroke={MARKER}
                strokeWidth={2}
                label={{
                  value: geneSymbol ?? "gene",
                  position: "top",
                  fontSize: 11,
                  fill: MARKER,
                }}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}

      {tab === "volcano" && (
        <ResponsiveContainer width="100%" height={260}>
          <ScatterChart margin={{ top: 6, right: 12, bottom: 24, left: 0 }}>
            <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="effect"
              tick={{ fontSize: 11 }}
              label={{
                value: data.effectColumn,
                position: "insideBottom",
                offset: -8,
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
            <ZAxis range={[24, 24]} />
            <Tooltip
              formatter={(v, name) => [
                typeof v === "number" ? fmt(v, 3) : String(v),
                String(name),
              ]}
              cursor={{ strokeDasharray: "3 3" }}
            />
            <Scatter
              name="background"
              data={data.volcanoPoints}
              fill={BACKGROUND_DOT}
              fillOpacity={0.6}
              isAnimationActive={false}
            />
            {geneScatter.length > 0 && (
              <Scatter
                name={geneSymbol ?? "gene"}
                data={geneScatter}
                fill={MARKER}
                shape="cross"
                isAnimationActive={false}
              />
            )}
          </ScatterChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
