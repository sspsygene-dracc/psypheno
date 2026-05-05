import { ALL_CONTROLS_SENTINEL_ID } from "@/lib/gene-query";

export type CentralGeneKind = "gene" | "control";

export interface SearchSuggestion {
  centralGeneId: number;
  // The text the user typed when this suggestion was produced. Used by
  // SearchBar to highlight the matching synonym in the dropdown — keep
  // it as the typed prefix, not the matched symbol.
  searchQuery: string;
  // What to show in the input box once this suggestion is selected.
  // Falls back to searchQuery if null. Prefer HGNC, then first mouse
  // symbol; matches the gene-resolution priority in CLAUDE.md.
  displayLabel: string | null;
  humanSymbol: string | null;
  mouseSymbols: string[] | null;
  humanSynonyms: string[] | null;
  mouseSynonyms: string[] | null;
  datasetCount: number;
  kind: CentralGeneKind;
}

/**
 * Build the synthetic "all controls" suggestion. Lives here (not in
 * lib/suggestions.ts) because the home page needs to construct it
 * client-side during URL hydration, and lib/suggestions.ts pulls in
 * better-sqlite3.
 */
export function buildAllControlsSuggestion(
  individualCount: number,
): SearchSuggestion {
  return {
    centralGeneId: ALL_CONTROLS_SENTINEL_ID,
    searchQuery: "CONTROL",
    displayLabel: "CONTROL",
    humanSymbol: "CONTROL",
    mouseSymbols: null,
    humanSynonyms: null,
    mouseSynonyms: null,
    datasetCount: individualCount,
    kind: "control",
  };
}
