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
    const q = ((req.query.q as string) || "").trim();

    // Build a UNION query across species to fetch symbols
    const species = ["human", "mouse", "zebrafish"] as const;
    const whereName = q.length > 0 ? "AND name LIKE ?" : "";
    const params: any[] = [];
    if (q.length > 0) {
      const like = `%${q}%`;
      // one param per species in UNION
      params.push(like, like, like);
    }

    const unionSql = species
      .map(
        (sp) =>
          `SELECT entrez_id AS entrezId, name, '${sp}' AS species FROM ${sp}_entrez_gene WHERE is_symbol = 1 ${whereName}`
      )
      .join("\nUNION ALL\n");

    // Fetch all candidate genes matching the query (needed to sort by dataset count)
    const allStmt = db.prepare(`SELECT * FROM (\n${unionSql}\n)`);
    const allGenes = allStmt.all(...params) as Array<{
      entrezId: number;
      name: string;
      species: string;
    }>;

    // Map to hold dataset counts per entrezId for all candidates
    const idToInfo = new Map<
      number,
      { name: string; species: string; datasetCount: number; datasets: Set<string> }
    >();
    for (const g of allGenes) {
      idToInfo.set(g.entrezId, {
        name: g.name,
        species: g.species,
        datasetCount: 0,
        datasets: new Set<string>(),
      });
    }

    const allIds = allGenes.map((g) => g.entrezId);

    if (allIds.length > 0) {
      // Read dataset->link tables mapping once
      const dataTables = db
        .prepare(`SELECT table_name, link_tables FROM data_tables`)
        .all() as Array<{ table_name: string; link_tables: string | null }>;

      for (const table of dataTables) {
        if (!table.link_tables) continue;

        const linkTables = table.link_tables
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
          .map((entry) => {
            const parts = entry.split(":");
            return parts.length >= 2 ? parts[1] : parts[0];
          });

        for (const linkTable of linkTables) {
          try {
            // Query in manageable chunks to respect SQLite parameter limits
            const chunkSize = 800;
            for (let i = 0; i < allIds.length; i += chunkSize) {
              const chunk = allIds.slice(i, i + chunkSize);
              const placeholders = chunk.map(() => "?").join(",");
              const stmt = db.prepare(
                `SELECT DISTINCT entrez_gene FROM ${linkTable} WHERE entrez_gene IN (${placeholders})`
              );
              const rows = stmt.all(...chunk) as Array<{ entrez_gene: number }>;
              for (const r of rows) {
                const info = idToInfo.get(r.entrez_gene);
                if (info && !info.datasets.has(table.table_name)) {
                  info.datasets.add(table.table_name);
                  info.datasetCount++;
                }
              }
            }
          } catch (err) {
            console.error(`Error querying link table ${linkTable}:`, err);
          }
        }
      }
    }

    // Build, filter to genes with at least one dataset, sort by datasetCount DESC then name ASC
    const sorted = Array.from(idToInfo.entries())
      .map(([entrezId, info]) => ({
        entrezId,
        name: info.name,
        species: info.species,
        datasetCount: info.datasetCount,
      }))
      .filter((g) => g.datasetCount > 0)
      .sort((a, b) => {
        if (b.datasetCount !== a.datasetCount) return b.datasetCount - a.datasetCount;
        return a.name.localeCompare(b.name);
      });

    const total = sorted.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const start = (page - 1) * pageSize;
    const genes = sorted.slice(start, start + pageSize);

    return res.status(200).json({ genes, page, pageSize, total, totalPages, query: q });
  } catch (err) {
    console.error("all-genes handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}

