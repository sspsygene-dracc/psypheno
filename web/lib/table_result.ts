export interface TableResult {
  tableName: string;
  shortLabel?: string | null;
  description: string | null;
  source?: string | null;
  assay?: string[] | null;
  fieldLabels?: Record<string, string> | null;
  displayColumns: string[];
  scalarColumns?: string[];
  publicationFirstAuthor?: string | null;
  publicationLastAuthor?: string | null;
  publicationYear?: number | null;
  publicationJournal?: string | null;
  publicationDoi?: string | null;
  rows: Record<string, unknown>[];
  totalRows?: number;
}
