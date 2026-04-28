import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TableResult } from "@/lib/table_result";

const POSITIVE = "#2563eb";
const NEGATIVE = "#ef4444";
const DEFAULT_LIMIT = 25;

const formatTableLabel = (t: TableResult): string =>
  t.mediumLabel ??
  t.tableName
    .replace(/_/g, " ")
    .replace(/\w\S*/g, (s) => s.charAt(0).toUpperCase() + s.slice(1));

const stripParenthetical = (s: string | null | undefined): string =>
  (s ?? "").replace(/\s*\(.*?\)\s*/g, "").trim();

type EffectBar = {
  key: string;
  label: string;
  effect: number;
  organism: string;
  assay: string;
};

function buildBars(data: TableResult[]): EffectBar[] {
  const bars: EffectBar[] = [];
  for (const t of data) {
    if (!t.effectColumn) continue;
    for (let i = 0; i < t.rows.length; i += 1) {
      const raw = t.rows[i][t.effectColumn];
      const num = raw == null ? null : Number(raw);
      if (num == null || !Number.isFinite(num)) continue;
      bars.push({
        key: `${t.tableName}|${i}`,
        label: formatTableLabel(t),
        effect: num,
        organism: stripParenthetical(t.organism) || "Unknown",
        assay: (t.assay && t.assay.length > 0 ? t.assay.join(", ") : "")
          .toString(),
      });
    }
  }
  bars.sort((a, b) => Math.abs(b.effect) - Math.abs(a.effect));
  return bars;
}

export default function CrossTableEffectBars({
  data,
  geneSymbol,
}: {
  data: TableResult[];
  geneSymbol?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const bars = useMemo(() => buildBars(data), [data]);

  const tablesContributing = useMemo(() => {
    const set = new Set<string>();
    for (const b of bars) set.add(b.label);
    return set.size;
  }, [bars]);

  if (bars.length === 0 || tablesContributing < 2) return null;

  const visible = showAll ? bars : bars.slice(0, DEFAULT_LIMIT);
  const truncated = bars.length > visible.length;

  return (
    <div
      style={{
        marginBottom: 16,
        border: "1px solid #dbeafe",
        borderRadius: 8,
        background: "#f8fafc",
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        style={{
          width: "100%",
          padding: "10px 14px",
          background: "none",
          border: "none",
          cursor: "pointer",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 14,
          fontWeight: 600,
          color: "#1e40af",
        }}
      >
        <span>
          Effect sizes across studies
          {geneSymbol ? ` for ${geneSymbol}` : ""} — {bars.length} row
          {bars.length !== 1 ? "s" : ""} in {tablesContributing} table
          {tablesContributing !== 1 ? "s" : ""}
        </span>
        <span style={{ fontSize: 12, color: "#6b7280" }}>
          {expanded ? "▲ Hide" : "▼ Show"}
        </span>
      </button>
      {expanded && (
        <div style={{ padding: "0 14px 14px" }}>
          <ResponsiveContainer
            width="100%"
            height={Math.max(120, visible.length * 22 + 60)}
          >
            <BarChart
              data={visible}
              layout="vertical"
              margin={{ top: 6, right: 24, bottom: 24, left: 0 }}
            >
              <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
              <XAxis
                type="number"
                tick={{ fontSize: 11 }}
                label={{
                  value: "effect size",
                  position: "insideBottom",
                  offset: -8,
                  fontSize: 12,
                }}
              />
              <YAxis
                type="category"
                dataKey="label"
                tick={{ fontSize: 11 }}
                width={220}
                interval={0}
              />
              <Tooltip
                formatter={(v) => [
                  typeof v === "number" ? v.toFixed(3) : String(v),
                  "effect",
                ]}
                labelFormatter={(label, payload) => {
                  const p = payload?.[0]?.payload as EffectBar | undefined;
                  if (!p) return String(label);
                  const ctx = [p.assay, p.organism].filter(Boolean).join(" · ");
                  return ctx ? `${label}\n${ctx}` : String(label);
                }}
              />
              <Bar dataKey="effect" isAnimationActive={false}>
                {visible.map((b) => (
                  <Cell
                    key={b.key}
                    fill={b.effect >= 0 ? POSITIVE : NEGATIVE}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          {truncated && (
            <div style={{ textAlign: "center", marginTop: 4 }}>
              <button
                type="button"
                onClick={() => setShowAll(true)}
                style={{
                  background: "none",
                  border: "none",
                  color: "#2563eb",
                  cursor: "pointer",
                  fontSize: 12,
                  textDecoration: "underline",
                }}
              >
                Show all {bars.length}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
