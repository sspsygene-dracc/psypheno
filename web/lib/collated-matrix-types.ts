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
  /** Pooled phenotype columns: the original measures this column combines. */
  contains?: Array<{ source: string; column: string }>;
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
  /**
   * Summary columns only (#234). `baseMetric` is the dataset's own metric — the
   * units of each cell's `best` — as opposed to `metric`, which is the summary
   * column's own count scale. `sigRule` names what `nSig` counted, since the
   * wide phenotype axis only has a nominal p where the others have an FDR.
   */
  baseMetric?: string;
  sigRule?: string;
}

export interface MatrixCell {
  /** The cell value in its column's metric units (frontend maps it to a color). */
  value: number;
  /**
   * Summary-mode only (#234): the raw counts behind a collapsed dataset column,
   * shown in the click popover. Sent only in `mode: "summary"` — at
   * `colsPerDataset: 200` these would add three numbers to ~10^5 cells that
   * nothing displays. `nSig` counts readouts passing the column's `sigRule`;
   * `best` is the strongest readout in the column's `baseMetric` units.
   */
  nSig?: number;
  nMeasured?: number;
  best?: number;
  /**
   * Expanded mode, significant-only sources: the source published only its
   * hits, and this pair is *inferred* "tested, not significant" — no value was
   * ever published, so `value` is meaningless (0). The basis says why:
   * - "screen": the perturbation has reported hits in the same context (e.g.
   *   cell type), and this readout was a hit for another perturbation there.
   * - "library": the perturbation is only on the paper's perturbation list (no
   *   reported row at all) — assumed tested in every context the table covers.
   */
  inferred?: InferredBasis;
  /**
   * Expanded mode, phenotype columns: this value also appears for this gene in
   * another study, which is named here, so it isn't independent evidence.
   */
  sharedWith?: string;
  /** Summary mode: how many of `nMeasured` readouts were inferred, and on what basis. */
  nInferred?: number;
  inferredBasis?: InferredBasis;
  /**
   * Collated mode (by readout, across studies): `k` of the `n` studies that
   * measured this (perturbed gene, readout gene) pair found it significant;
   * `nUp` / `nDown` split the `k` by effect direction (they may not add up to
   * `k` when a study has no effect column). `nInferred` (shared with summary
   * mode) counts studies whose measurement was inferred. `value` = k / n.
   */
  k?: number;
  n?: number;
  nUp?: number;
  nDown?: number;
}

export type InferredBasis = "screen" | "library";

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

export type MatrixMode = "expanded" | "summary" | "collated";

/** One study behind a collated cell — GET /api/collated-cell. */
export interface CollatedContribution {
  study: string;
  studyLabel: string;
  /** Source table(s) of the study that measured the pair (comma-joined). */
  sourceTables: string;
  /** How many tests (cell types, conditions, methods) the study ran on the pair. */
  nTests: number;
  minFdr: number | null;
  bestP: number | null;
  /** Effect at the study's most significant test (log fold change etc.). */
  effect: number | null;
  significant: boolean;
  /** Set when the study never reported the pair (significant-only source). */
  inferredBasis: InferredBasis | null;
}

/** One original measurement behind a pooled phenotype cell. */
export interface PhenotypeTest {
  source: string;
  sourceTable: string;
  column: string;
  p: number;
  fdr: number;
  effect: number | null;
}

export interface CollatedCellResponse {
  contributions: CollatedContribution[];
  /** Pooled phenotype columns only. */
  tests?: PhenotypeTest[];
}

export interface CollatedMatrixMeta {
  /** Which view produced this response. */
  mode: MatrixMode;
  /**
   * False when the overview DB predates the summary tables (#234) — the page
   * disables the Summary control rather than rendering an empty matrix.
   */
  summaryAvailable: boolean;
  /** False when the overview DB predates the collated tables. */
  collatedAvailable: boolean;
  /** Collated mode: the studies pooled into its columns. */
  collatedStudies?: Array<{ study: string; label: string }>;
  /**
   * Collated mode: labels of studies that feed more than one section, so the
   * per-section study counts add up to more than `collatedStudies.length`.
   */
  collatedStudiesInSeveralSections?: string[];
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
