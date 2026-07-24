import { NextApiRequest, NextApiResponse } from "next";
import { getDb } from "@/lib/db";
import { setReadCacheHeaders } from "@/lib/cache-headers";
import { sanitizeIdentifier, parseLinkTablesForDirection } from "@/lib/gene-query";

/**
 * GET /api/collated-matrix — aggregation backend for the collated cross-modality
 * overview table ("red table", psypheno #212, epic #220).
 *
 * Returns, for **every experimentally-perturbed gene** (a central gene in a
 * `perturbed`-direction link table of a real KO/KD/i or mutation screen), a
 * per-modality cell status plus a count and the contributing table names for
 * drill-down (#214). Modalities come from the taxonomy shipped in #211 (the
 * `modalities` table / GET /api/modalities).
 *
 * "Experimentally perturbed" is narrower than "in any perturbed-direction link
 * table": curated/phenotype annotation DBs (ClinVar/SFARI/MGI), GRN-inference
 * networks, and RNA-expression readout tables also carry perturbed links but
 * are NOT experimental perturbations — they're filtered out (see the exclusion
 * block below). The response's `excludedSources` lists what was dropped.
 *
 * Cell status (per gene × modality), aggregated across all perturbation tables
 * whose `assay` maps to that modality. Over the gene's joined rows:
 *   nSig     = rows where any pvalue/fdr column < 0.05
 *   nData    = rows where any pvalue/fdr column IS NOT NULL
 *   nAssayed = joined rows (gene present in the perturbed link table)
 * Precedence: nSig>0 → "significant"; else nData>0 → "data"; else nAssayed>0 →
 * "assayed_null"; else "none". Significance predicate ( < 0.05 over pvalue+fdr
 * columns) matches web/pages/api/significant-rows.ts. Controls (central_gene
 * kind='control') are excluded, mirroring the meta-analysis collector.
 *
 * All aggregation is set-based SQL (one grouped query per perturbation table),
 * not per-gene loops.
 */

export type CellStatus = "significant" | "data" | "assayed_null" | "none";

interface Cell {
  status: CellStatus;
  count: number;
  tableNames: string[];
}

interface GeneRow {
  centralGeneId: number;
  humanSymbol: string | null;
  cells: Record<string, Cell>;
}

interface ModalityColumn {
  key: string;
  label: string;
  alwaysShow: boolean;
  isEmpty: boolean;
}

// Per (gene, modality) accumulator collected across contributing tables.
interface Accum {
  nSig: number;
  nData: number;
  nAssayed: number;
  tableNames: Set<string>;
}

interface ModalityRow {
  key: string;
  label: string;
  assay_types: string;
  always_show: number;
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  try {
    const db = getDb();

    // 1. Ordered modality taxonomy (same query as /api/modalities). A missing
    //    table (older DB build) yields an empty matrix rather than a 500.
    let modalityRows: ModalityRow[] = [];
    try {
      modalityRows = db
        .prepare(
          "SELECT key, label, assay_types, always_show FROM modalities " +
            "ORDER BY sort_order ASC"
        )
        .all() as ModalityRow[];
    } catch {
      modalityRows = [];
    }

    const modalities = modalityRows.map((m) => ({
      key: m.key,
      label: m.label,
      alwaysShow: Boolean(m.always_show),
      assayTypes: (() => {
        try {
          return JSON.parse(m.assay_types) as string[];
        } catch {
          return [];
        }
      })(),
    }));

    // Invert the taxonomy: assay-type key → modality keys that cover it. One
    // assay can map to multiple modalities in principle; today it's 1:1.
    const assayToModalities = new Map<string, string[]>();
    for (const m of modalities) {
      for (const a of m.assayTypes) {
        const list = assayToModalities.get(a) ?? [];
        list.push(m.key);
        assayToModalities.set(a, list);
      }
    }

    // 2. All data tables that expose a perturbed-direction link table.
    const tables = db
      .prepare(
        `SELECT table_name, assay, categories, pvalue_column, fdr_column, link_tables
           FROM data_tables`
      )
      .all() as Array<{
      table_name: string;
      assay: string | null;
      categories: string | null;
      pvalue_column: string | null;
      fdr_column: string | null;
      link_tables: string | null;
    }>;

    // gene_id → modality key → accumulator
    const geneAccum = new Map<number, Map<string, Accum>>();
    // gene universe: every gene experimentally perturbed in ≥1 dataset.
    const geneUniverse = new Set<number>();
    // Perturbed-direction sources dropped from the row universe, for transparency
    // (surfaced in the response so #213 / reviewers can see what was excluded).
    const excludedSources: Array<{ tableName: string; reason: string }> = [];

    for (const t of tables) {
      const linkTables = parseLinkTablesForDirection(
        t.link_tables || "",
        "perturbed"
      );
      if (linkTables.length === 0) continue;

      // Assay → modality keys this table contributes to. Tables whose assay
      // maps to no modality (curated / phenotype annotation DBs — deliberately
      // excluded from the taxonomy, e.g. ClinVar / SFARI / MGI, which also carry
      // perturbed-direction links) contribute neither rows nor cells: skip them.
      const assayKeys = (t.assay || "")
        .split(",")
        .map((a) => a.trim())
        .filter(Boolean);
      const modalityKeys = new Set<string>();
      for (const a of assayKeys) {
        for (const k of assayToModalities.get(a) ?? []) modalityKeys.add(k);
      }
      if (modalityKeys.size === 0) continue;

      // Rows must be *experimentally* perturbed genes (psypheno #212, "experimental
      // only" — confirmed with Johannes). Two data-driven signals distinguish real
      // KO/KD/i screens from tables whose `perturbed` link is inference or a
      // readout gene-list, which otherwise flood the matrix with non-perturbed
      // genes (~914 → ~199 rows):
      //   - GRN-inference tables (categories include "GRN inference"): the
      //     `perturbed` direction is *inferred* TF→target regulatory edges, not a
      //     physically perturbed gene (e.g. Fleck 2023 — 720 inferred TFs).
      //   - Pure RNA-expression readout tables (assay = expression): a perturbed
      //     link there is an incidental region/condition gene list, not a screened
      //     panel (e.g. hsc DE_results `region_genes` = whole CNV-region gene
      //     lists, ~115 genes). Consequence: with no experimental perturbed-
      //     direction expression data, the RNA-expression modality carries zero
      //     rows and auto-hides — see the note in the response's `modalities`.
      const categories = (t.categories || "").toLowerCase();
      if (categories.includes("grn inference")) {
        excludedSources.push({ tableName: t.table_name, reason: "grn_inference" });
        continue;
      }
      if (assayKeys.includes("expression")) {
        excludedSources.push({
          tableName: t.table_name,
          reason: "expression_readout",
        });
        continue;
      }

      // p-value + FDR columns (each may be comma-separated). Invalid identifiers
      // are skipped rather than aborting the whole request.
      const statCols: string[] = [];
      for (const raw of [t.pvalue_column, t.fdr_column]) {
        if (!raw) continue;
        for (const c of raw.split(",").map((s) => s.trim()).filter(Boolean)) {
          try {
            statCols.push(sanitizeIdentifier(c));
          } catch {
            /* skip unusable column */
          }
        }
      }

      let baseTable: string;
      try {
        baseTable = sanitizeIdentifier(t.table_name);
      } catch {
        continue;
      }

      const dataPredicate = statCols.length
        ? statCols.map((c) => `t.${c} IS NOT NULL`).join(" OR ")
        : "0";
      const sigPredicate = statCols.length
        ? statCols.map((c) => `(t.${c} IS NOT NULL AND t.${c} < 0.05)`).join(" OR ")
        : "0";

      // One grouped, set-based pass per perturbed link table.
      for (const lt of linkTables) {
        const query = `
          SELECT lt.central_gene_id AS gene_id,
                 COUNT(*) AS n_assayed,
                 SUM(CASE WHEN (${dataPredicate}) THEN 1 ELSE 0 END) AS n_data,
                 SUM(CASE WHEN (${sigPredicate}) THEN 1 ELSE 0 END) AS n_sig
            FROM ${baseTable} t
            JOIN ${lt} lt ON t.id = lt.id
            JOIN central_gene cg ON cg.id = lt.central_gene_id
           WHERE cg.kind != 'control'
           GROUP BY lt.central_gene_id`;

        let rows: Array<{
          gene_id: number;
          n_assayed: number;
          n_data: number;
          n_sig: number;
        }>;
        try {
          rows = db.prepare(query).all() as typeof rows;
        } catch (innerErr) {
          console.error(
            `collated-matrix: query failed for ${baseTable} / ${lt}`,
            innerErr
          );
          continue;
        }

        for (const r of rows) {
          geneUniverse.add(r.gene_id);

          let perModality = geneAccum.get(r.gene_id);
          if (!perModality) {
            perModality = new Map();
            geneAccum.set(r.gene_id, perModality);
          }
          for (const mk of modalityKeys) {
            let acc = perModality.get(mk);
            if (!acc) {
              acc = { nSig: 0, nData: 0, nAssayed: 0, tableNames: new Set() };
              perModality.set(mk, acc);
            }
            acc.nSig += r.n_sig;
            acc.nData += r.n_data;
            acc.nAssayed += r.n_assayed;
            acc.tableNames.add(t.table_name);
          }
        }
      }
    }

    // 3. Resolve human symbols for the gene universe in one query.
    const geneIds = [...geneUniverse];
    const symbolById = new Map<number, string | null>();
    if (geneIds.length > 0) {
      const placeholders = geneIds.map(() => "?").join(",");
      const symRows = db
        .prepare(
          `SELECT id, human_symbol FROM central_gene WHERE id IN (${placeholders})`
        )
        .all(...geneIds) as Array<{ id: number; human_symbol: string | null }>;
      for (const s of symRows) symbolById.set(s.id, s.human_symbol);
    }

    const statusOf = (acc: Accum | undefined): Cell => {
      if (!acc) return { status: "none", count: 0, tableNames: [] };
      const tableNames = [...acc.tableNames].sort();
      if (acc.nSig > 0)
        return { status: "significant", count: acc.nSig, tableNames };
      if (acc.nData > 0) return { status: "data", count: acc.nData, tableNames };
      if (acc.nAssayed > 0)
        return { status: "assayed_null", count: acc.nAssayed, tableNames };
      return { status: "none", count: 0, tableNames };
    };

    // 4. Build gene rows (one cell per modality), alphabetical by symbol.
    const genes: GeneRow[] = geneIds
      .map((id) => {
        const perModality = geneAccum.get(id);
        const cells: Record<string, Cell> = {};
        for (const m of modalities) {
          cells[m.key] = statusOf(perModality?.get(m.key));
        }
        return {
          centralGeneId: id,
          humanSymbol: symbolById.get(id) ?? null,
          cells,
        };
      })
      .sort((a, b) => {
        // Null / empty symbols sort last; otherwise case-insensitive A→Z.
        const as = a.humanSymbol || "";
        const bs = b.humanSymbol || "";
        if (!as && !bs) return a.centralGeneId - b.centralGeneId;
        if (!as) return 1;
        if (!bs) return -1;
        return as.localeCompare(bs, "en", { sensitivity: "base" });
      });

    // 5. Per-modality emptiness (no gene has a non-"none" cell). The frontend
    //    (#215) auto-hides !alwaysShow && isEmpty; alwaysShow columns always render.
    const modalityColumns: ModalityColumn[] = modalities.map((m) => ({
      key: m.key,
      label: m.label,
      alwaysShow: m.alwaysShow,
      isEmpty: !genes.some((g) => g.cells[m.key]?.status !== "none"),
    }));

    setReadCacheHeaders(res);
    return res
      .status(200)
      .json({ modalities: modalityColumns, genes, excludedSources });
  } catch (err) {
    console.error("collated-matrix handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
