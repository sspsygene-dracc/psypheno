export interface TableResult {
  tableName: string;
  displayColumns: string[];
  rows: Record<string, unknown>[];
}
