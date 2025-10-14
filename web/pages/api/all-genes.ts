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

    // Get all unique genes across all species and count dataset occurrences
    const species = ["human", "mouse", "zebrafish"];
    const geneMap = new Map<
      number,
      { name: string; species: string; datasetCount: number; datasets: Set<string> }
    >();

    for (const sp of species) {
      const tableName = `${sp}_entrez_gene`;
      
      // Get all genes for this species
      const genes = db
        .prepare(
          `SELECT DISTINCT entrez_id, name 
           FROM ${tableName} 
           WHERE is_symbol = 1
           ORDER BY name ASC`
        )
        .all() as Array<{ entrez_id: number; name: string }>;

      for (const gene of genes) {
        if (!geneMap.has(gene.entrez_id)) {
          geneMap.set(gene.entrez_id, {
            name: gene.name,
            species: sp,
            datasetCount: 0,
            datasets: new Set(),
          });
        }
      }
    }

    // Now count datasets for each gene
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
          const genes = db
            .prepare(`SELECT DISTINCT entrez_gene FROM ${linkTable}`)
            .all() as Array<{ entrez_gene: number }>;

          for (const { entrez_gene } of genes) {
            const geneInfo = geneMap.get(entrez_gene);
            if (geneInfo && !geneInfo.datasets.has(table.table_name)) {
              geneInfo.datasets.add(table.table_name);
              geneInfo.datasetCount++;
            }
          }
        } catch (err) {
          console.error(`Error querying link table ${linkTable}:`, err);
        }
      }
    }

    // Convert to array and sort by dataset count (descending)
    const genes = Array.from(geneMap.entries())
      .map(([entrezId, info]) => ({
        entrezId,
        name: info.name,
        species: info.species,
        datasetCount: info.datasetCount,
      }))
      .filter(g => g.datasetCount > 0) // Only include genes that appear in at least one dataset
      .sort((a, b) => b.datasetCount - a.datasetCount || a.name.localeCompare(b.name));

    return res.status(200).json({ genes });
  } catch (err) {
    console.error("all-genes handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}

