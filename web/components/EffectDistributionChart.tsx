import { useEffect, useMemo, useState } from "react";
import {
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
  fdr: number | null;
  rowKey: string;
};

type VolcanoPoint = {
  effect: number;
  negLog10P: number;
  fdr: number | null;
  topByP: boolean;
};

type DistributionResponse = {
  effectColumn: string;
  pvalueColumn: string;
  fdrColumn: string | null;
  nTotal: number;
  nNonNull: number;
  volcanoPoints: VolcanoPoint[];
  geneRows: GeneRow[];
};

const SIG_THRESHOLD = 0.05;

const COLOR_UP = "#dc2626"; // red
const COLOR_DOWN = "#2563eb"; // blue
const COLOR_NS = "#cbd5e1"; // light grey
const COLOR_GENE = "#f59e0b"; // amber for queried gene
const COLOR_GENE_OUTLINE = "#111827";

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

  // Hooks must run unconditionally; compute on whatever data we have, even
  // when null, and gate the render below.
  const seriesByCategory = useMemo(() => {
    const byCat: Record<Category, VolcanoPoint[]> = { up: [], down: [], ns: [] };
    if (!data) return byCat;
    for (const p of data.volcanoPoints) {
      const cat = classify(p.effect, p.fdr, null);
      byCat[cat].push(p);
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
        <div>
          {data.effectColumn} vs −log<sub>10</sub>({data.pvalueColumn}) · n ={" "}
          {data.nNonNull.toLocaleString()} · sig: {sigLabel}
        </div>
        <div style={{ display: "flex", gap: 12 }}>
          <LegendDot color={COLOR_DOWN} label={`Down (${downCount})`} />
          <LegendDot color={COLOR_NS} label={`Not sig. (${nsCount})`} />
          <LegendDot color={COLOR_UP} label={`Up (${upCount})`} />
          {geneScatter.length > 0 && (
            <LegendDot
              color={COLOR_GENE}
              outline={COLOR_GENE_OUTLINE}
              label={`${geneSymbol ?? "gene"} (${geneScatter.length})`}
            />
          )}
        </div>
      </div>

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
          <ZAxis range={[20, 20]} />
          <ReferenceLine x={0} stroke="#9ca3af" strokeDasharray="4 4" />
          <Tooltip
            content={(props) => {
              const payload = (
                props as unknown as {
                  payload?: Array<{ payload?: Record<string, unknown> }>;
                }
              ).payload;
              const p = payload?.[0]?.payload as
                | (VolcanoPoint & {
                    pvalue?: number | null;
                    rowKey?: string;
                  })
                | undefined;
              if (!p) return null;
              const isGene = "rowKey" in p && p.rowKey != null;
              return (
                <div
                  style={{
                    background: "#ffffff",
                    border: "1px solid #d1d5db",
                    borderRadius: 6,
                    padding: "8px 10px",
                    fontSize: 12,
                    boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
                  }}
                >
                  {isGene && (
                    <div
                      style={{ fontWeight: 600, marginBottom: 4 }}
                    >
                      {geneSymbol ?? "queried gene"}
                    </div>
                  )}
                  <div>
                    {data.effectColumn}:{" "}
                    <strong>{fmt(p.effect, 3)}</strong>
                  </div>
                  <div>
                    {data.pvalueColumn}:{" "}
                    <strong>
                      {fmt(
                        (p as { pvalue?: number | null }).pvalue ??
                          (p.negLog10P != null
                            ? Math.pow(10, -p.negLog10P)
                            : null),
                        2,
                      )}
                    </strong>
                  </div>
                  {data.fdrColumn && (
                    <div>
                      {data.fdrColumn}: <strong>{fmt(p.fdr, 2)}</strong>
                    </div>
                  )}
                </div>
              );
            }}
            cursor={{ strokeDasharray: "3 3" }}
          />
          <Scatter
            name="ns"
            data={seriesByCategory.ns}
            fill={COLOR_NS}
            isAnimationActive={false}
          />
          <Scatter
            name="down"
            data={seriesByCategory.down}
            fill={COLOR_DOWN}
            isAnimationActive={false}
          />
          <Scatter
            name="up"
            data={seriesByCategory.up}
            fill={COLOR_UP}
            isAnimationActive={false}
          />
          {geneScatter.length > 0 && (
            <Scatter
              name="gene"
              data={geneScatter}
              fill={COLOR_GENE}
              stroke={COLOR_GENE_OUTLINE}
              strokeWidth={1.5}
              isAnimationActive={false}
              shape="circle"
              legendType="circle"
            />
          )}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function LegendDot({
  color,
  outline,
  label,
}: {
  color: string;
  outline?: string;
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
          border: outline ? `1.5px solid ${outline}` : "none",
          borderRadius: 9999,
        }}
      />
      {label}
    </span>
  );
}
