import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import {
  sanitizeIdentifier,
  parseDisplayColumns,
  buildGeneQuery,
  queryPage,
  validateSortColumn,
  buildOrderByClause,
  type ApiSortMode,
} from "@/lib/gene-query";
import {
  getEnsemblSymbolMap,
  resolveEnsgsInRows,
} from "@/lib/ensembl-symbol-resolver";

const bodySchema = z.object({
  tableName: z.string().min(1),
  page: z.number().min(1),
  perturbedCentralGeneId: z.number().nullable().optional(),
  targetCentralGeneId: z.number().nullable().optional(),
  sortBy: z.string().optional(),
  sortMode: z.enum(["asc", "desc", "asc_abs", "desc_abs"]).optional(),
});

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const parse = bodySchema.safeParse(req.body);
  if (!parse.success) {
    return res.status(400).json({ error: "Invalid request body" });
  }

  const { tableName, page, perturbedCentralGeneId, targetCentralGeneId } = parse.data;

  if (!perturbedCentralGeneId && !targetCentralGeneId) {
    return res.status(400).json({ error: "At least one gene ID is required" });
  }

  try {
    const db = getDb();

    const t = db
      .prepare(
        `SELECT table_name, display_columns, scalar_columns, link_tables FROM data_tables WHERE table_name = ?`
      )
      .get(tableName) as {
        table_name: string;
        display_columns: string;
        scalar_columns: string | null;
        link_tables: string | null;
      } | undefined;

    if (!t) {
      return res.status(400).json({ error: `Table not found: ${tableName}` });
    }

    const baseTable = sanitizeIdentifier(t.table_name);
    const displayCols = parseDisplayColumns(t.display_columns);

    if (displayCols.length === 0) {
      return res.status(400).json({ error: "Table has no display columns" });
    }

    const query = buildGeneQuery({
      baseTable,
      displayCols,
      linkTablesRaw: t.link_tables || "",
      perturbedCentralGeneId,
      targetCentralGeneId,
    });

    if (!query) {
      return res.status(400).json({ error: "Cannot query this table with the given parameters" });
    }

    // Build ORDER BY clause if sort params provided
    let orderBy: string | undefined;
    if (parse.data.sortBy && parse.data.sortMode) {
      const validCol = validateSortColumn(parse.data.sortBy, displayCols);
      if (validCol) {
        const scalarCols = new Set(
          (t.scalar_columns || "").split(",").map((s) => s.trim()).filter(Boolean)
        );
        let mode = parse.data.sortMode as ApiSortMode;
        // Only allow abs sort on scalar columns
        const isAbsMode = mode === "asc_abs" || mode === "desc_abs";
        if (isAbsMode && !scalarCols.has(validCol)) {
          mode = mode === "asc_abs" ? "asc" : "desc";
        }
        orderBy = buildOrderByClause({ column: validCol, mode, tableAlias: "b" });
      }
    }

    const result = queryPage(db, query.selectCols, query.fromAndWhere, query.params, page, orderBy);
    const symbolMap = getEnsemblSymbolMap(db);
    const translatedResult = {
      ...result,
      rows: resolveEnsgsInRows(result.rows, symbolMap),
    };

    return res.status(200).json({ tableName, ...translatedResult });
  } catch (err) {
    console.error("gene-table-page handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
