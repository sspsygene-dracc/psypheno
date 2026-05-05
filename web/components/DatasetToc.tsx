import { useEffect, useMemo, useRef, useState } from "react";

export type TocItem = {
  tableName: string;
  shortLabel?: string | null;
  mediumLabel?: string | null;
  longLabel?: string | null;
  assay?: string[] | null;
};

type AssayGroup = {
  assayKey: string;
  label: string;
  items: TocItem[];
};

const formatTableName = (item: TocItem) =>
  item.mediumLabel ??
  item.tableName
    .replace(/_/g, " ")
    .replace(/\w\S*/g, (txt) => txt.charAt(0).toUpperCase() + txt.slice(1));

export function useAssayGroups(
  items: TocItem[],
  assayTypeLabels: Record<string, string>
): AssayGroup[] {
  return useMemo(() => {
    const groupMap = new Map<string, TocItem[]>();
    for (const item of items) {
      const key = item.assay?.[0] || "_other";
      if (!groupMap.has(key)) groupMap.set(key, []);
      groupMap.get(key)!.push(item);
    }

    const ordered: AssayGroup[] = [];
    for (const [k, groupItems] of groupMap) {
      ordered.push({
        assayKey: k,
        label: k === "_other" ? "Other" : (assayTypeLabels[k] ?? k),
        items: groupItems,
      });
    }

    // Sort groups alphabetically, "_other" last
    ordered.sort((a, b) => {
      if (a.assayKey === "_other") return 1;
      if (b.assayKey === "_other") return -1;
      return a.label.localeCompare(b.label);
    });

    // Sort items within each group alphabetically
    for (const group of ordered) {
      group.items.sort((a, b) =>
        formatTableName(a).localeCompare(formatTableName(b))
      );
    }

    return ordered;
  }, [items, assayTypeLabels]);
}

export { type AssayGroup };

export default function DatasetToc({
  groups,
  anchorPrefix,
  title = "Datasets",
  style: extraStyle,
}: {
  groups: AssayGroup[];
  anchorPrefix: string;
  title?: string;
  style?: React.CSSProperties;
}) {
  const hasMultipleGroups = groups.length > 1;

  // Scroll-spy: highlight the TOC entry whose section is currently in
  // the viewport. Use IntersectionObserver with a rootMargin that biases
  // "active" to whatever's near the top of the viewport, so a long
  // section near the bottom doesn't keep stealing focus from the one
  // the user is actually reading.
  const [activeId, setActiveId] = useState<string | null>(null);
  // Track each section's intersection ratio so we can pick the most
  // visible one, not just the most recently changed.
  const ratios = useRef<Map<string, number>>(new Map());

  const allTableNames = useMemo(
    () => groups.flatMap((g) => g.items.map((i) => i.tableName)),
    [groups],
  );

  useEffect(() => {
    if (allTableNames.length === 0) return;
    const elements = allTableNames
      .map((name) => document.getElementById(`${anchorPrefix}${name}`))
      .filter((el): el is HTMLElement => el !== null);
    if (elements.length === 0) return;

    const localRatios = ratios.current;
    const recompute = () => {
      let bestId: string | null = null;
      let bestRatio = 0;
      for (const [id, ratio] of localRatios) {
        if (ratio > bestRatio) {
          bestRatio = ratio;
          bestId = id;
        }
      }
      setActiveId(bestId);
    };

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.target.id;
          if (entry.isIntersecting) {
            localRatios.set(id, entry.intersectionRatio);
          } else {
            localRatios.delete(id);
          }
        }
        recompute();
      },
      {
        // Top 60% of the viewport is the "active zone" — anything below
        // is treated as not yet read. The wide threshold list lets the
        // observer fire as a section gradually scrolls in/out.
        rootMargin: "0px 0px -40% 0px",
        threshold: [0, 0.1, 0.25, 0.5, 0.75, 1],
      },
    );

    for (const el of elements) observer.observe(el);
    return () => {
      observer.disconnect();
      localRatios.clear();
    };
  }, [allTableNames, anchorPrefix]);

  const scrollTo = (id: string) => {
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <nav
      style={{
        width: 220,
        flexShrink: 0,
        background: "#f9fafb",
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        padding: "14px 0",
        position: "sticky",
        top: 16,
        maxHeight: "calc(100vh - 48px)",
        overflowY: "auto",
        // Without this, wheel events that hit the TOC's scroll limit chain
        // up to the document and scroll the whole page — surprising when
        // you're navigating a long dataset list.
        overscrollBehavior: "contain",
        ...extraStyle,
      }}
    >
      <div
        style={{
          padding: "0 14px 10px",
          fontWeight: 600,
          fontSize: 13,
          color: "#6b7280",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        {title}
      </div>
      {groups.map((group) => (
        <div key={group.assayKey}>
          {hasMultipleGroups && (
            <div
              style={{
                padding: "8px 14px 4px",
                fontSize: 12,
                fontWeight: 600,
                color: "#1e40af",
                textTransform: "uppercase",
                letterSpacing: "0.04em",
                borderTop: "1px solid #e5e7eb",
                marginTop: 4,
              }}
            >
              {group.label}
            </div>
          )}
          {group.items.map((item) => {
            const id = `${anchorPrefix}${item.tableName}`;
            const isActive = activeId === id;
            return (
              <button
                key={item.tableName}
                onClick={() => scrollTo(id)}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: hasMultipleGroups
                    ? "6px 14px 6px 22px"
                    : "8px 14px",
                  background: isActive ? "#dbeafe" : "transparent",
                  border: "none",
                  borderLeft: isActive
                    ? "3px solid #2563eb"
                    : "3px solid transparent",
                  cursor: "pointer",
                  fontSize: 13,
                  color: "#2563eb",
                  fontWeight: isActive ? 700 : 400,
                  lineHeight: 1.4,
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.background = "#e5e7eb";
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.background = "transparent";
                }}
              >
                {formatTableName(item)}
              </button>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
