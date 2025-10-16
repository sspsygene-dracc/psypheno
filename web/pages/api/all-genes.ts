import { NextApiRequest, NextApiResponse } from "next";
import { getDb } from "@/lib/db";

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  try {
    const db = getDb();

    // Query params
    const page = Math.max(1, parseInt((req.query.page as string) || "1", 10));
    const pageSize = Math.min(
      200,
      Math.max(1, parseInt((req.query.pageSize as string) || "50", 10))
    );
    const qRaw = ((req.query.q as string) || "").trim();
    const q = qRaw.toLowerCase();
    const likePrefix = `${q}%`;

    // Compose filters
    const filters: string[] = ["cg.num_datasets > 0"]; // always require datasets
    const params: any[] = [];
    if (q.length > 0) {
      filters.unshift(
        `(
          LOWER(cg.human_symbol) LIKE ?
          OR LOWER(cg.mouse_symbols) LIKE ?
          OR EXISTS (
            SELECT 1 FROM synonyms s
            WHERE s.central_gene_id = cg.id AND LOWER(s.synonym) LIKE ?
          )
        )`
      );
      params.push(likePrefix, likePrefix, likePrefix);
    }
    const whereSql = filters.length > 0 ? `WHERE ${filters.join(" AND ")}` : "";

    // Total count (only genes with at least one dataset)
    const countSql = `SELECT COUNT(*) as cnt
                      FROM central_gene cg
                      ${whereSql}`;
    const countRow = db.prepare(countSql).get(...params) as
      | { cnt: number }
      | undefined;
    const total = countRow?.cnt ?? 0;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const offset = (page - 1) * pageSize;

    const dataSql = `SELECT cg.id AS entrezId,
                            COALESCE(cg.human_symbol, cg.mouse_symbols, CAST(cg.id AS TEXT)) AS name,
                            CASE WHEN cg.human_symbol IS NOT NULL AND cg.mouse_symbols IS NOT NULL THEN 'human/mouse'
                                 WHEN cg.human_symbol IS NOT NULL THEN 'human'
                                 WHEN cg.mouse_symbols IS NOT NULL THEN 'mouse'
                                 ELSE 'unknown' END AS species,
                            cg.num_datasets AS datasetCount
                     FROM central_gene cg
                     ${whereSql}
                     ORDER BY cg.num_datasets DESC, name ASC
                     LIMIT ? OFFSET ?`;

    const rows = db.prepare(dataSql).all(...params, pageSize, offset) as Array<{
      entrezId: number;
      name: string;
      species: string;
      datasetCount: number;
    }>;

    const genes = rows;

    return res
      .status(200)
      .json({ genes, page, pageSize, total, totalPages, query: qRaw });
  } catch (err) {
    console.error("all-genes handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
