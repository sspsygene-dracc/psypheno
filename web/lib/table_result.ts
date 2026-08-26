export interface TableResult {
  tableName: string;
  shortLabel?: string | null;
  mediumLabel?: string | null;
  longLabel?: string | null;
  description: string | null;
  source?: string | null;
  assay?: string[] | null;
  organism?: string | null;
  fieldLabels?: Record<string, string> | null;
  // Per-column display header overrides (#210). Distinct from fieldLabels
  // (which are the "?" tooltip text).
  columnLabels?: Record<string, string> | null;
  displayColumns: string[];
  scalarColumns?: string[];
  geneColumns?: string[];
  // Subset of geneColumns whose link-table entry direction is "perturbed".
  // Anything in geneColumns not listed here is treated as a target column.
  // Used by DataTable to pick `/?perturbed=` vs `/?target=` for cell links.
  perturbedGeneColumns?: string[];
  pvalueColumn?: string | null;
  fdrColumn?: string | null;
  effectColumn?: string | null;
  publicationFirstAuthor?: string | null;
  publicationLastAuthor?: string | null;
  publicationAuthorCount?: number | null;
  publicationYear?: number | null;
  publicationJournal?: string | null;
  publicationDoi?: string | null;
  // Instances this dataset's config.yaml allows it on (#225). Drives the
  // "not on production" badge. null when the DB predates #225.
  destinations?: string[] | null;
  rows: Record<string, unknown>[];
  totalRows?: number;
}
