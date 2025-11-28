export interface TableResult {
  tableName: string;
  shortLabel?: string | null;
  description: string | null;
  displayColumns: string[];
  rows: Record<string, unknown>[];
  totalRows?: number;
}
