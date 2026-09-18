import {
  descriptionParagraphs,
  parseInlineMarkup,
} from "@/lib/inline-markup";

/**
 * Dataset description with `**bold**` and paragraph breaks.
 * Bold is darker than the surrounding gray body so a caveat actually reads
 * as a caveat (gene-search results, publications, downloads).
 */
export default function DatasetDescription({ text }: { text: string }) {
  const paragraphs = descriptionParagraphs(text);
  return (
    <>
      {paragraphs.map((paragraph, i) => (
        <div key={i} style={{ marginTop: i === 0 ? 0 : 8 }}>
          {parseInlineMarkup(paragraph).map((span, j) =>
            span.kind === "bold" ? (
              <strong
                key={j}
                style={{ fontWeight: 700, color: "#111827" }}
              >
                {span.text}
              </strong>
            ) : (
              <span key={j}>{span.text}</span>
            ),
          )}
        </div>
      ))}
    </>
  );
}
