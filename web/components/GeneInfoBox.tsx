import { type ReactNode } from "react";

export type LlmResult = {
  pubmedLinks: string | null;
  summary: string | null;
  status: string;
  searchDate: string | null;
};

export function renderPubmedLinks(linksStr: string): ReactNode {
  const linkRegex =
    /\[([^\]]+)\]\((https:\/\/pubmed\.ncbi\.nlm\.nih\.gov\/\d+\/?)\)/g;
  const urls: string[] = [];
  let match;
  while ((match = linkRegex.exec(linksStr)) !== null) {
    urls.push(match[2]);
  }
  if (urls.length === 0) return <>{linksStr}</>;
  return (
    <span>
      {urls.map((url, i) => (
        <span key={i}>
          {i > 0 && " "}
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "#2563eb", textDecoration: "underline" }}
          >
            [{i + 1}]
          </a>
        </span>
      ))}
    </span>
  );
}

export default function GeneInfoBox({
  geneDescription,
  llmResult,
}: {
  geneDescription?: string | null;
  llmResult?: LlmResult | null;
}) {
  const hasLlmResults = llmResult && llmResult.status === "results";
  const hasLlmNoResults = llmResult && llmResult.status === "no_results";
  const hasLlmNotSearched =
    llmResult && (!llmResult.status || llmResult.status === "not_searched");
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        fontSize: 13,
      }}
    >
      {geneDescription ? (
        <div
          style={{
            marginBottom: hasLlmResults ? 4 : 0,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            Gene description (RefSeq)
          </div>
          <p
            style={{
              margin: 0,
            }}
          >
            {geneDescription}
          </p>
        </div>
      ) : (
        <span style={{ color: "#9ca3af", fontStyle: "italic" }}>
          No RefSeq gene description available for this gene.
        </span>
      )}
      {hasLlmResults && (
        <>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            LLM-generated summary
            {llmResult.searchDate && (
              <span
                style={{
                  fontWeight: 400,
                  color: "#6b7280",
                  marginLeft: 8,
                  fontSize: 12,
                }}
              >
                (generated {llmResult.searchDate})
              </span>
            )}
          </div>
          <p style={{ margin: 0, color: "#374151" }}>
            {llmResult.summary}
            {llmResult.pubmedLinks && (
              <> {renderPubmedLinks(llmResult.pubmedLinks)}</>
            )}
          </p>
          <p style={{ margin: "4px 0 0", color: "#6b7280", fontSize: 12 }}>
            LLM-generated results may be unreliable and may include
            hallucinations. Always verify against primary sources.
          </p>
        </>
      )}
      {hasLlmNoResults && (
        <span style={{ color: "#9ca3af", fontStyle: "italic" }}>
          LLM search returned no relevant results for this gene.
        </span>
      )}
      {hasLlmNotSearched && (
        <span style={{ color: "#9ca3af", fontStyle: "italic" }}>
          No LLM search has been performed for this gene yet.
        </span>
      )}
    </div>
  );
}
