/**
 * Response contract for GET /api/collated-matrix — the collated cross-modality
 * overview table ("red table", epic #220).
 *
 * The producer/consumer boundary lives here rather than in the API route so the
 * matrix components import the same declarations the handler builds, instead of
 * re-declaring structurally-identical copies that drift silently.
 *
 * The matrix has two kinds of column, described by `sections`:
 *
 * - a **status** section is one column whose cell is a status glyph aggregated
 *   over every source table of that modality (the original #212 shape);
 * - an **expanded** section (#222) fans out into one `pvalue` sub-column per
 *   measured target gene, forming a heatmap. RNA expression is the first one.
 *
 * `columns` is the flat render order. Every column's `key` is also the key
 * under which a gene's cell appears in `MatrixGeneRow.cells`; a status column's
 * key is its modality key, an expanded sub-column's key is prefixed
 * (`expr:SHANK3`). A missing key means "no data" — expanded sections are sparse,
 * status columns are not.
 */

export type CellStatus = "significant" | "data" | "assayed_null" | "none";

export interface MatrixSection {
  key: string;
  label: string;
  kind: "status" | "expanded";
  /** Number of entries in `columns` belonging to this section. */
  span: number;
  /** Expensive low-output modalities render even when entirely empty (#215). */
  alwaysShow: boolean;
  isEmpty: boolean;
}

export interface MatrixStatusColumn {
  section: string;
  key: string;
  label: string;
  kind: "status";
}

export interface MatrixPvalueColumn {
  section: string;
  key: string;
  /** The measured target gene (the column's short label). */
  label: string;
  kind: "pvalue";
  /**
   * How many distinct perturbed groups this target gene is FDR-significant in —
   * CNV regions for the ASD organoid table, perturbed genes elsewhere. Drives
   * both column eligibility (≥2) and the most-convergent-first render order.
   */
  nSigGroups: number;
  /** Source dataset table name — the column's dataset identity. */
  sourceTable: string;
  /** Dataset short label, shown once per dataset band above the columns. */
  sourceLabel: string;
  /** Fuller dataset identity for the band's (i) tooltip. */
  sourceMediumLabel: string | null;
  /** Dataset source/citation string, appended to the band tooltip. */
  sourceCitation: string | null;
}

export type MatrixColumn = MatrixStatusColumn | MatrixPvalueColumn;

export interface MatrixStatusCell {
  status: CellStatus;
  /** Row count for the winning status tier, not a total across tiers. */
  count: number;
  /** Contributing source tables, for drill-down (#214). */
  tableNames: string[];
}

export interface MatrixPvalueCell {
  /** -log10 of the most significant raw p-value, clamped to [1, 20]. */
  negLogP: number;
}

export type MatrixCellValue = MatrixStatusCell | MatrixPvalueCell;

export interface MatrixGeneRow {
  centralGeneId: number;
  humanSymbol: string | null;
  cells: Record<string, MatrixCellValue>;
}

export interface CollatedMatrixMeta {
  /** Columns-per-dataset cap used for this response (after clamping). */
  colsPerDataset: number;
  /** Total expanded (pvalue) columns actually returned across all datasets. */
  expandedColumnCount: number;
  /** Expanded columns available at the eligibility floor, before the top-K cap. */
  expandedColumnsAvailable: number;
  /** True when some dataset had more eligible columns than the cap showed. */
  expandedColumnsTruncated: boolean;
  /** Build-time eligibility floor (min significant groups; typically 2). */
  minSigGroupsFloor: number;
  /** Largest columns-per-dataset the build materialized (cap ceiling). */
  materializeTopM: number;
  /** False when serving the live fallback against an un-materialized DB. */
  materialized: boolean;
  builtAt: string | null;
}

export interface CollatedMatrixResponse {
  sections: MatrixSection[];
  columns: MatrixColumn[];
  genes: MatrixGeneRow[];
  meta: CollatedMatrixMeta;
}

export function isPvalueCell(cell: MatrixCellValue): cell is MatrixPvalueCell {
  return "negLogP" in cell;
}

/**
 * Gene-row sort used by the API and mirrored by the matrix component's
 * "sort by symbol" mode: case-insensitive A→Z, unnamed genes last.
 */
export function compareGeneRows(a: MatrixGeneRow, b: MatrixGeneRow): number {
  const as = a.humanSymbol || "";
  const bs = b.humanSymbol || "";
  if (!as && !bs) return a.centralGeneId - b.centralGeneId;
  if (!as) return 1;
  if (!bs) return -1;
  return as.localeCompare(bs, "en", { sensitivity: "base" });
}
