import type { CSSProperties } from "react";
import InfoTooltip from "@/components/InfoTooltip";
import { type DatasetLink, linkDisplayText } from "@/lib/links";

type Props = {
  link: DatasetLink;
  anchorStyle?: CSSProperties;
  tooltipSize?: number;
};

export default function DatasetLinkAnchor({
  link,
  anchorStyle,
  tooltipSize = 14,
}: Props) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center" }}>
      <a
        href={link.url}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: "#2563eb",
          textDecoration: "underline",
          ...anchorStyle,
        }}
      >
        {linkDisplayText(link)}
      </a>
      {link.description && (
        <InfoTooltip text={link.description} size={tooltipSize} />
      )}
    </span>
  );
}
