export interface TableResult {
  tableName: string;
  shortLabel?: string | null;
  mediumLabel?: string | null;
  longLabel?: string | null;
  description: string | null;
  source?: string | null;
  assay?: string[] | null;
  fieldLabels?: Record<string, string> | null;
  displayColumns: string[];
  scalarColumns?: string[];
  pvalueColumn?: string | null;
  fdrColumn?: string | null;
  publicationFirstAuthor?: string | null;
  publicationLastAuthor?: string | null;
  publicationAuthorCount?: number | null;
  publicationYear?: number | null;
  publicationJournal?: string | null;
  publicationDoi?: string | null;
  rows: Record<string, unknown>[];
  totalRows?: number;
}
