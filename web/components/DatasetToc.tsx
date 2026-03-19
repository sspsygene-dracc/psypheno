import { useMemo } from "react";

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
          {group.items.map((item) => (
            <button
              key={item.tableName}
              onClick={() => scrollTo(`${anchorPrefix}${item.tableName}`)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: hasMultipleGroups
                  ? "6px 14px 6px 22px"
                  : "8px 14px",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                fontSize: 13,
                color: "#2563eb",
                lineHeight: 1.4,
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "#e5e7eb")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "transparent")
              }
            >
              {formatTableName(item)}
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}
