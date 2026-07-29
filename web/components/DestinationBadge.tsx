/**
 * "Not on production" marker for a dataset (#225).
 *
 * A dataset appears on an instance only if its config.yaml's `deployTo` names
 * it. This badge surfaces that on every screen where a dataset is listed, so a
 * wrangler who has just loaded an embargoed dataset onto dev can see its
 * status without opening the config — and, more importantly, notices *before*
 * running a promote that a dataset they expected to be held back is not.
 *
 * Renders nothing when the dataset IS cleared for prod, and nothing when the
 * destinations are unknown (a DB built before #225). Absence of a badge
 * therefore means "on prod, or unknowable" — the badge only ever appears to
 * warn, never to reassure.
 */

import { restrictionLabel } from "@/lib/destinations";

export type BadgeSize = "inline" | "compact";

const TITLES = {
  "Internal only":
    "deployTo: [dev, int] — this dataset is not cleared for the public " +
    "site. A promote to prod will leave it out.",
  "Dev only":
    "deployTo: [dev] — this dataset is not published to the internal or " +
    "public sites. A promote to int or prod will leave it out.",
} as const;

function describe(destinations: string[]): {
  label: "Internal only" | "Dev only";
  title: string;
} | null {
  const label = restrictionLabel(destinations);
  if (!label) return null;
  return { label, title: TITLES[label] };
}

export default function DestinationBadge({
  destinations,
  size = "inline",
}: {
  destinations?: string[] | null;
  size?: BadgeSize;
}) {
  const info = describe(destinations ?? []);
  if (!info) return null;

  const compact = size === "compact";
  return (
    <span
      title={info.title}
      style={{
        display: "inline-block",
        verticalAlign: "middle",
        marginLeft: compact ? 4 : 8,
        padding: compact ? "0 5px" : "2px 8px",
        borderRadius: 999,
        // Amber rather than red: this is the *expected* state for an
        // embargoed dataset, not an error.
        background: "#fef3c7",
        border: "1px solid #fcd34d",
        color: "#92400e",
        fontSize: compact ? 10 : 12,
        fontWeight: 700,
        lineHeight: compact ? "15px" : "18px",
        whiteSpace: "nowrap",
        letterSpacing: "0.01em",
      }}
    >
      {compact ? (info.label === "Internal only" ? "int" : "dev") : info.label}
    </span>
  );
}

