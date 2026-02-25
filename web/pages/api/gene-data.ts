import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";
import { performance } from "perf_hooks";

const bodySchema = z.object({
  centralGeneId: z.number().min(0),
});

function sanitizeIdentifier(id: string): string {
  // Allow only alphanumeric and underscore to avoid SQL injection via identifiers
  if (!/^\w+$/.test(id)) throw new Error(`Invalid identifier: ${id}`);
  return id;
}

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

  const centralGeneId = parse.data.centralGeneId;
  const tHandler = performance.now();

  try {
    const db = getDb();

    const tables = db
      .prepare(
        `SELECT table_name, short_label, description, source, assay, field_labels, gene_columns, display_columns, scalar_columns, link_tables, publication_first_author, publication_last_author, publication_year, publication_journal, publication_doi FROM data_tables ORDER BY id ASC`
      )
      .all() as Array<{
        table_name: string;
        short_label: string | null;
        description: string | null;
        source: string | null;
        assay: string | null;
        field_labels: string | null;
        gene_columns: string;
        display_columns: string;
        scalar_columns: string | null;
        link_tables: string | null;
        publication_first_author: string | null;
        publication_last_author: string | null;
        publication_year: number | null;
        publication_journal: string | null;
        publication_doi: string | null;
      }>;

    const ROW_LIMIT = 200;

    const results: Array<{
      tableName: string;
      shortLabel: string | null;
      description: string | null;
      source: string | null;
      assay: string[];
      fieldLabels: Record<string, string> | null;
      displayColumns: string[];
      scalarColumns: string[];
      publicationFirstAuthor: string | null;
      publicationLastAuthor: string | null;
      publicationYear: number | null;
      publicationJournal: string | null;
      publicationDoi: string | null;
      rows: Record<string, unknown>[];
      totalRows: number;
    }> = [];

    for (const t of tables) {
      const baseTable = sanitizeIdentifier(t.table_name);
      const displayCols = (t.display_columns || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map(sanitizeIdentifier);

      if (displayCols.length === 0) continue;

      // Parse link tables list which may contain entries like "alias:table_name" or "alias:table_name:isPerturbed:isTarget"
      // We only need the actual link table names to join on base.id = link.id and filter link.central_gene_id
      const linkTables = (t.link_tables || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((entry) => {
          const parts = entry.split(":");
          const tableName = parts.length >= 2 ? parts[1] : parts[0];
          return sanitizeIdentifier(tableName);
        });

      // Build SQL using subqueries so SQLite can drive from the indexed link tables
      // instead of scanning the base table
      const selectCols = displayCols.map((c) => `b.${c}`).join(", ");
      const params: Array<string> = [];

      if (linkTables.length === 0) {
        // No way to filter for this table
        continue;
      }

      // Build a UNION of subqueries on link tables, each using the central_gene_id index
      const subqueries = linkTables.map((lt) => {
        params.push(String(centralGeneId));
        return `SELECT id FROM ${lt} WHERE central_gene_id = ?`;
      });
      const idSubquery = subqueries.length === 1
        ? subqueries[0]
        : subqueries.join(" UNION ");
      const fromAndWhere = `FROM ${baseTable} b WHERE b.id IN (${idSubquery})`;

      try {
        // Fetch one extra row to detect whether more rows exist beyond the limit
        const dataSql = `SELECT DISTINCT ${selectCols} ${fromAndWhere} LIMIT ${ROW_LIMIT + 1}`;

        // Query plan
        const plan = db.prepare(`EXPLAIN QUERY PLAN ${dataSql}`).all(...params);
        console.log(`[gene-data] table=${baseTable} QUERY PLAN:`, JSON.stringify(plan));

        const tq = performance.now();
        const allRows = db.prepare(dataSql).all(...params) as Record<string, unknown>[];
        const queryMs = performance.now() - tq;
        console.log(`[gene-data] table=${baseTable} SELECT rows=${allRows.length} time=${queryMs.toFixed(1)}ms`);

        if (allRows.length === 0) continue;

        const hasMore = allRows.length > ROW_LIMIT;
        const rows = hasMore ? allRows.slice(0, ROW_LIMIT) : allRows;

        // Only run the expensive COUNT query when there are more rows than the limit
        let totalRows: number;
        if (hasMore) {
          const countSql = `SELECT COUNT(*) as cnt FROM (SELECT DISTINCT ${selectCols} ${fromAndWhere})`;
          const tc = performance.now();
          totalRows = (db.prepare(countSql).get(...params) as { cnt: number }).cnt;
          const countMs = performance.now() - tc;
          console.log(`[gene-data] table=${baseTable} COUNT=${totalRows} time=${countMs.toFixed(1)}ms`);
        } else {
          totalRows = rows.length;
        }

        let fieldLabels: Record<string, string> | null = null;
        if (t.field_labels) {
          try {
            fieldLabels = JSON.parse(t.field_labels);
          } catch {
            fieldLabels = null;
          }
        }
        const assay = (t.assay || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
        results.push({
          tableName: t.table_name,
          shortLabel: t.short_label ?? null,
          description: t.description ?? null,
          source: t.source ?? null,
          assay,
          fieldLabels,
          displayColumns: displayCols,
          scalarColumns: (t.scalar_columns || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          publicationFirstAuthor: t.publication_first_author ?? null,
          publicationLastAuthor: t.publication_last_author ?? null,
          publicationYear: t.publication_year ?? null,
          publicationJournal: t.publication_journal ?? null,
          publicationDoi: t.publication_doi ?? null,
          rows,
          totalRows,
        });
      } catch (innerErr) {
        // Skip tables that fail (e.g., column missing) to keep response robust
        // eslint-disable-next-line no-console
        console.error(`Query failed for table ${baseTable}`, innerErr);
      }
    }

    const totalMs = performance.now() - tHandler;
    console.log(`[gene-data] TOTAL time=${totalMs.toFixed(1)}ms tables_with_results=${results.length}`);
    return res.status(200).json({ centralGeneId, results });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("gene-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
