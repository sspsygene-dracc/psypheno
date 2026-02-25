import { NextApiRequest, NextApiResponse } from "next";
import { z } from "zod";
import { getDb } from "@/lib/db";

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

      // Build SQL
      const selectCols = displayCols.map((c) => `b.${c}`).join(", ");

      let sql = `SELECT ${selectCols} FROM ${baseTable} b`;
      const params: Array<string> = [];

      if (linkTables.length > 0) {
        const whereParts: string[] = [];
        linkTables.forEach((lt, idx) => {
          const alias = `lt${idx}`;
          sql += ` LEFT JOIN ${lt} ${alias} ON b.id = ${alias}.id`;
          whereParts.push(`${alias}.central_gene_id = ?`);
          params.push(String(centralGeneId));
        });
        sql += ` WHERE ${whereParts.join(" OR ")}`;
      } else {
        // No way to filter for this table
        continue;
      }

      try {
        const stmt = db.prepare(sql);
        const rows = stmt.all(...params) as Record<string, unknown>[];
        if (rows.length > 0) {
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
          });
        }
      } catch (innerErr) {
        // Skip tables that fail (e.g., column missing) to keep response robust
        // eslint-disable-next-line no-console
        console.error(`Query failed for table ${baseTable}`, innerErr);
      }
    }

    return res.status(200).json({ centralGeneId, results });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("gene-data handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
