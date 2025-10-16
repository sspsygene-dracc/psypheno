export interface SearchSuggestion {
  centralGeneId: number;
  searchQuery: string;
  humanSymbol: string | null;
  mouseSymbols: string[] | null;
  humanSynonyms: string[] | null;
  mouseSynonyms: string[] | null;
  datasetCount: number;
}
