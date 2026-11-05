import Link from "next/link";
import type { ReactNode } from "react";
import type { OrthologNotes } from "@/lib/orthologs";

// One-line notes under a gene panel's header for mouse genes with several
// human orthologs and no single best match: on the mouse gene, its candidate
// human genes; on a human candidate, the mouse genes that point at it. Each
// name links to that gene's search in the same direction as the panel.
export default function OrthologNote({
  notes,
  direction,
}: {
  notes: OrthologNotes | null | undefined;
  direction: "perturbed" | "target";
}) {
  if (!notes || (notes.candidates.length === 0 && notes.candidateOf.length === 0)) {
    return null;
  }
  const href = (symbol: string) => `/?${direction}=${encodeURIComponent(symbol)}`;
  const linkStyle = { color: "#2563eb", textDecoration: "underline" };
  const join = (items: ReactNode[]) =>
    items.map((item, i) => (
      <span key={i}>
        {i > 0 && ", "}
        {item}
      </span>
    ));
  return (
    <div
      data-testid="ortholog-note"
      style={{ fontSize: 13, color: "#4b5563", marginBottom: 8 }}
    >
      {notes.candidates.length > 0 && (
        <div>
          Several human orthologs, no single best match:{" "}
          {join(
            notes.candidates.map((c) =>
              c.centralGeneId != null ? (
                <Link href={href(c.symbol)} style={linkStyle}>
                  {c.symbol}
                </Link>
              ) : (
                <span title="Not in any loaded dataset">{c.symbol}</span>
              ),
            ),
          )}
        </div>
      )}
      {notes.candidateOf.length > 0 && (
        <div>
          Also a candidate ortholog of mouse{" "}
          {join(
            notes.candidateOf.map((m) => (
              <Link href={href(m.mouseSymbol)} style={linkStyle}>
                {m.mouseSymbol}
              </Link>
            )),
          )}{" "}
          (several human orthologs, no single best match)
        </div>
      )}
    </div>
  );
}
