import { NextApiRequest, NextApiResponse } from "next";
import { getDb } from "@/lib/db";
import type { Dataset } from "@/components/DatasetItem";
import { parseDatasetLinks, type DatasetLink } from "@/lib/links";

export type PublicationTableEntry = {
  tableName: string;
  label: string;
  organism: string | null;
  links: DatasetLink[];
  dataset: Dataset;
};

export type PublicationEntry = {
  doi: string;
  pmid: string | null;
  year: number | null;
  journal: string | null;
  firstAuthor: string | null;
  lastAuthor: string | null;
  authorCount: number | null;
  authors: string[];
  organisms: string[];
  assays: string[];
  sspsygeneGrants: string[];
  tables: PublicationTableEntry[];
};

export default async function handler(
  _req: NextApiRequest,
  res: NextApiResponse,
) {
  try {
    const db = getDb();

    const rows = db
      .prepare(
        `SELECT
           table_name, short_label, medium_label, long_label, description,
           gene_columns, gene_species, display_columns, scalar_columns,
           link_tables, links, categories, source, assay, organism,
           publication_doi, publication_pmid, publication_year, publication_journal,
           publication_first_author, publication_last_author, publication_author_count,
           publication_authors, publication_sspsygene_grants
         FROM data_tables
         WHERE publication_doi IS NOT NULL
         ORDER BY publication_year DESC, publication_first_author ASC, table_name ASC`,
      )
      .all() as Array<{
      table_name: string;
      short_label: string | null;
      medium_label: string | null;
      long_label: string | null;
      description: string | null;
      gene_columns: string;
      gene_species: string;
      display_columns: string;
      scalar_columns: string;
      link_tables: string | null;
      links: string | null;
      categories: string | null;
      source: string | null;
      assay: string | null;
      organism: string | null;
      publication_doi: string;
      publication_pmid: string | null;
      publication_year: number | null;
      publication_journal: string | null;
      publication_first_author: string | null;
      publication_last_author: string | null;
      publication_author_count: number | null;
      publication_authors: string | null;
      publication_sspsygene_grants: string | null;
    }>;

    const byDoi = new Map<string, PublicationEntry>();

    const parseStringArray = (raw: string | null): string[] => {
      if (!raw) return [];
      try {
        const v = JSON.parse(raw);
        return Array.isArray(v)
          ? v.filter((x): x is string => typeof x === "string")
          : [];
      } catch {
        return [];
      }
    };

    for (const r of rows) {
      const existing = byDoi.get(r.publication_doi);
      const entry: PublicationEntry =
        existing ??
        {
          doi: r.publication_doi,
          pmid: r.publication_pmid,
          year: r.publication_year,
          journal: r.publication_journal,
          firstAuthor: r.publication_first_author,
          lastAuthor: r.publication_last_author,
          authorCount: r.publication_author_count,
          authors: parseStringArray(r.publication_authors),
          organisms: [],
          assays: [],
          sspsygeneGrants: parseStringArray(r.publication_sspsygene_grants),
          tables: [],
        };
      if (!existing) byDoi.set(r.publication_doi, entry);
      // Merge per-table assays into the publication-level set.
      const tableAssays = (r.assay || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      for (const a of tableAssays) {
        if (!entry.assays.includes(a)) entry.assays.push(a);
      }
      const tableLinks = parseDatasetLinks(r.links);
      const dataset: Dataset = {
        table_name: r.table_name,
        short_label: r.short_label,
        medium_label: r.medium_label,
        long_label: r.long_label,
        description: r.description,
        gene_columns: r.gene_columns,
        gene_species: r.gene_species,
        display_columns: r.display_columns,
        scalar_columns: r.scalar_columns,
        link_tables: r.link_tables,
        links: tableLinks,
        categories: r.categories,
        source: r.source,
        assay: r.assay,
        organism: r.organism,
        publication_first_author: r.publication_first_author,
        publication_last_author: r.publication_last_author,
        publication_author_count: r.publication_author_count,
        publication_year: r.publication_year,
        publication_journal: r.publication_journal,
        publication_doi: r.publication_doi,
      };
      entry.tables.push({
        tableName: r.table_name,
        label: r.medium_label || r.table_name,
        organism: r.organism,
        links: tableLinks,
        dataset,
      });
      if (r.organism && !entry.organisms.includes(r.organism)) {
        entry.organisms.push(r.organism);
      }
    }

    return res.status(200).json({ publications: Array.from(byDoi.values()) });
  } catch (err) {
    console.error("publications handler error", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
