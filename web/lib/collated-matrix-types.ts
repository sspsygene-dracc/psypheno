/**
 * Response contract for GET /api/collated-matrix — the collated cross-modality
 * overview table ("red table", epic #220, #213).
 *
 * The producer/consumer boundary lives here so the matrix components import the
 * same declarations the handler builds, instead of re-declaring structurally
 * identical copies that drift silently.
 *
 * Every modality is **expanded** (#213 removed the aggregated "status" columns):
 * a section fans out into one value sub-column per measured target gene (genes)
 * or per phenotype (behavioral parameter, cell subcluster, brain region). Each
 * column carries a `metric` naming its color scale; each cell carries a single
 * `value` in that metric's units. `columns` is the flat render order; every
 * column's `key` is also the key under which a gene's cell appears in
 * `MatrixGeneRow.cells`. A missing key means "no data" (the matrix is sparse).
 */

export interface MatrixSection {
  /** Modality key (e.g. "expression", "behavior"). */
  key: string;
  /** Modality label (e.g. "RNA expression", "Behavioral"). */
  label: string;
  /** Number of entries in `columns` belonging to this section. */
  span: number;
}

export interface MatrixColumn {
  /** Modality key this column belongs to. */
  section: string;
  /** Cell-lookup key: `${prefix}:${sourceTable}:${columnValue}`. */
  key: string;
  /** The column's short label — a target gene or a phenotype. */
  label: string;
  /** Color-scale metric id (see web/lib/matrix-color-scales.ts). */
  metric: string;
  /** True when `label` is a gene (→ links to a target-gene search). */
  columnIsGene: boolean;
  /**
   * How many distinct perturbed groups this column is significant in (gene
   * columns) or how many genes have data (phenotype columns). Drives render
   * order and the header tooltip.
   */
  nSigGroups: number;
  /** Source dataset table name — the column's dataset identity + Full-datasets link. */
  sourceTable: string;
  /** Dataset author-year label, shown once per dataset band above the columns. */
  sourceLabel: string;
  /** Fuller dataset identity for the band's hover tooltip. */
  sourceMediumLabel: string | null;
  /** Dataset source/citation string, appended to the band tooltip. */
  sourceCitation: string | null;
}

export interface MatrixCell {
  /** The cell value in its column's metric units (frontend maps it to a color). */
  value: number;
}

export interface MatrixGeneRow {
  centralGeneId: number;
  humanSymbol: string | null;
  cells: Record<string, MatrixCell>;
}

/** A metric present in the response — drives one auto-generated legend bar. */
export interface MetricPresence {
  id: string;
  /** Per-dataset domain override, or null → use the registry default. */
  domain: [number, number] | null;
}

export interface CollatedMatrixMeta {
  /** Columns-per-dataset cap used for this response (after clamping). */
  colsPerDataset: number;
  /** Total value columns actually returned across all datasets. */
  expandedColumnCount: number;
  /** Columns available at the eligibility floor, before the top-K cap. */
  expandedColumnsAvailable: number;
  /** True when some dataset had more eligible columns than the cap showed. */
  expandedColumnsTruncated: boolean;
  /** Build-time gene-target eligibility floor (min significant groups; typically 2). */
  minSigGroupsFloor: number;
  /** Largest columns-per-dataset the build materialized (cap ceiling). */
  materializeTopM: number;
  /** False when the overview DB isn't built/attached (matrix is then empty). */
  materialized: boolean;
  builtAt: string | null;
  /** Distinct metrics present, for the auto-generated per-metric legend bars. */
  metrics: MetricPresence[];
}

export interface CollatedMatrixResponse {
  sections: MatrixSection[];
  columns: MatrixColumn[];
  genes: MatrixGeneRow[];
  meta: CollatedMatrixMeta;
}

/**
 * Gene-row sort used by the API: case-insensitive A→Z, unnamed genes last.
 */
export function compareGeneRows(a: MatrixGeneRow, b: MatrixGeneRow): number {
  const as = a.humanSymbol || "";
  const bs = b.humanSymbol || "";
  if (!as && !bs) return a.centralGeneId - b.centralGeneId;
  if (!as) return 1;
  if (!bs) return -1;
  return as.localeCompare(bs, "en", { sensitivity: "base" });
}
