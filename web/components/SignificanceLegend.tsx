import type { CSSProperties } from "react";
import { SIGNIFICANCE_THRESHOLD } from "@/components/DataTable";
import { SIGNIFICANT_ROW } from "@/lib/palette";

/**
 * Explains the green bar and tint DataTable applies to significant rows. Render it
 * anywhere a DataTable is shown with highlighting on — users otherwise have no
 * way to know what the green means.
 */
export default function SignificanceLegend({
  style,
}: {
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        padding: "10px 16px",
        fontSize: 13,
        color: "#374151",
        display: "flex",
        alignItems: "center",
        gap: 8,
        ...style,
      }}
    >
      <span
        aria-hidden="true"
        style={{
          display: "inline-block",
          width: 14,
          height: 14,
          background: SIGNIFICANT_ROW.background,
          border: "1px solid #d1d5db",
          boxShadow: `inset 3px 0 0 ${SIGNIFICANT_ROW.accent}`,
          borderRadius: 3,
          flexShrink: 0,
        }}
      />
      <span>
        Rows marked with a green bar have FDR or p &lt; {SIGNIFICANCE_THRESHOLD}{" "}
        (FDR is used when available).
      </span>
    </div>
  );
}
