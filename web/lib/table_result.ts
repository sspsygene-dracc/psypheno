export interface TableResult {
  tableName: string;
  description: string | null;
  displayColumns: string[];
  rows: Record<string, unknown>[];
}
