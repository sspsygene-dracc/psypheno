/**
 * Tiny markup for dataset descriptions: `**bold**` only.
 *
 * Descriptions are authored in config.yaml and rendered as React text, so
 * this never interprets HTML. A newline (YAML folded scalars turn a blank
 * line into one) starts a new paragraph; a trailing newline does not.
 */

export type InlineSpan =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string };

const BOLD = /\*\*([^*]+)\*\*/g;

export function parseInlineMarkup(input: string): InlineSpan[] {
  const spans: InlineSpan[] = [];
  let last = 0;
  for (const match of input.matchAll(BOLD)) {
    const start = match.index ?? 0;
    if (start > last) {
      spans.push({ kind: "text", text: input.slice(last, start) });
    }
    spans.push({ kind: "bold", text: match[1] });
    last = start + match[0].length;
  }
  if (last < input.length) {
    spans.push({ kind: "text", text: input.slice(last) });
  }
  if (spans.length === 0) {
    spans.push({ kind: "text", text: input });
  }
  return spans;
}

/** Split a description into paragraphs. Empty input yields no paragraphs. */
export function descriptionParagraphs(input: string): string[] {
  return input
    .split("\n")
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
}
