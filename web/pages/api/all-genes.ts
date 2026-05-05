import { NextApiRequest, NextApiResponse } from "next";
import { getDb } from "@/lib/db";
import { SearchSuggestion } from "@/state/SearchSuggestion";

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
    const filters: string[] = [
      "cg.num_datasets > 0",     // always require datasets
      "cg.kind = 'gene'",        // exclude controls from the gene browser
    ];
    const params: any[] = [];
    if (q.length > 0) {
      filters.unshift(
        `(
          LOWER(cg.human_symbol) LIKE ?
          OR LOWER(cg.mouse_symbols) LIKE ?
          OR EXISTS (
            SELECT 1 FROM extra_gene_synonyms s
            WHERE s.central_gene_id = cg.id AND LOWER(s.synonym) LIKE ?
          )
          OR EXISTS (
            SELECT 1 FROM extra_mouse_symbols s
            WHERE s.central_gene_id = cg.id AND LOWER(s.symbol) LIKE ?
          )
        )`
      );
      params.push(likePrefix, likePrefix, likePrefix, likePrefix);
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

    // Sort params
    const VALID_SORT_COLUMNS: Record<string, { sql: string; defaultDir: "ASC" | "DESC" }> = {
      human_symbol: { sql: "cg.human_symbol", defaultDir: "ASC" },
      num_datasets: { sql: "cg.num_datasets", defaultDir: "DESC" },
    };
    const sortByRaw = (req.query.sortBy as string) || "num_datasets";
    const sortDirRaw = (req.query.sortDir as string) || "";
    const sortEntry = VALID_SORT_COLUMNS[sortByRaw] ?? VALID_SORT_COLUMNS["num_datasets"];
    const sortDir = sortDirRaw === "asc" ? "ASC" : sortDirRaw === "desc" ? "DESC" : sortEntry.defaultDir;
    const nullsLast = sortDir === "ASC" ? "NULLS LAST" : "NULLS FIRST";
    const tiebreaker = sortByRaw === "human_symbol"
      ? ", cg.num_datasets DESC"
      : ", cg.human_symbol ASC";

    const dataSql = `SELECT cg.id,
                     cg.human_symbol,
                     cg.mouse_symbols,
                     cg.human_synonyms,
                     cg.mouse_synonyms,
                     cg.num_datasets AS dataset_count
                     FROM central_gene cg
                     ${whereSql}
                     ORDER BY ${sortEntry.sql} ${sortDir} ${nullsLast}${tiebreaker}
                     LIMIT ? OFFSET ?`;

    const rows = db.prepare(dataSql).all(...params, pageSize, offset) as Array<{
      id: number;
      human_symbol: string | null;
      mouse_symbols: string | null;
      human_synonyms: string | null;
      mouse_synonyms: string | null;
      dataset_count: number;
    }>;

    const genes: SearchSuggestion[] = rows.map((r) => {
      const mouseSymbols = r.mouse_symbols
        ? r.mouse_symbols.split(",").filter(Boolean)
        : null;
      return {
        centralGeneId: r.id,
        searchQuery: "",
        displayLabel: r.human_symbol ?? mouseSymbols?.[0] ?? null,
        humanSymbol: r.human_symbol,
        mouseSymbols,
        humanSynonyms: r.human_synonyms
          ? r.human_synonyms.split(",").filter(Boolean)
          : null,
        mouseSynonyms: r.mouse_synonyms
          ? r.mouse_synonyms.split(",").filter(Boolean)
          : null,
        datasetCount: r.dataset_count,
        kind: "gene",  // /api/all-genes filters to kind='gene' above
      };
    });

    return res
      .status(200)
      .json({ genes, page, pageSize, total, totalPages, query: qRaw });
  } catch (err) {
    console.error("all-genes handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
