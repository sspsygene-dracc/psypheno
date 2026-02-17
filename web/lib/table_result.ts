export interface TableResult {
  tableName: string;
  shortLabel?: string | null;
  description: string | null;
  source?: string | null;
  assay?: string[] | null;
  fieldLabels?: Record<string, string> | null;
  displayColumns: string[];
  scalarColumns?: string[];
  rows: Record<string, unknown>[];
  totalRows?: number;
}
