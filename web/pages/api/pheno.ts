import type { NextApiRequest, NextApiResponse } from 'next';
import { getDb, buildLimit, buildOrderBy } from '../../lib/db';

type Row = Record<string, unknown>;

function queryForPage(page?: string | string[] | undefined) {
  switch (page) {
    case 'deg':
      return {
        sql:
          'select hgnc.symbol, m.gene, m.cellType, m.logFC, m.PValue, m.perturbation, m.target from mousePerturb4Tf as m, hgnc where hgnc.hgnc_id=m.hgnc_id order by perturbation;',
        fields: [
          'Perturbed Gene',
          'Mouse Effect Gene',
          'Cell Type',
          'LogFC',
          'pVal',
          'Guide',
          'Perturbed Gene (mouse)'
        ],
        title: 'Gene expression changes'
      };
    case 'comp':
      return {
        sql: 'SELECT symbol, subcluster, PropRatio, FDR FROM comp, hgnc where comp.hgnc_id=hgnc.hgnc_id;',
        fields: ['Perturbed gene', 'Cell Type', 'Ratio change', 'FDR'],
        title: 'Cell type composition changes'
      };
    case 'sizes':
      return {
        sql:
          'select symbol, Forebrain, Optic_Tectum, Thalamus, Hypothalamus, Cerebellum, Hindbrain, Habenula, Posterior_Tuberculum,Mutant_Experiment_Sample from zebraAsdSizes as z, hgnc where hgnc.hgnc_id=z.hgnc_id;',
        fields: [
          'KO gene (Human)',
          'Foreb Size',
          'Optic Tec Size',
          'Thamalus',
          'Hypoth',
          'Cereb',
          'Hindb',
          'Haben',
          'Poster Tuber',
          'Assay Name'
        ],
        title: 'Zebrafish brain region sizes'
      };
    case 'perturbFishAstr':
      return {
        sql:
          'SELECT symbol, gene, LFC, qVal from perturbFishAstro as p, hgnc where hgnc.hgnc_id=p.hgnc_id;',
        fields: ['Perturbed gene', 'Changed Gene', 'LFC', 'qVal'],
        title: 'Perturb-fish expression changes'
      };
    case 'all':
      return { sql: null, fields: [], title: 'Integrated assays' };
    default:
      return { sql: null, fields: [], title: 'Phenotypes' };
  }
}

function getMerged(): { data: Record<string, { table: string; rows: unknown[][]; headers: string[] }[]> } {
  const db = getDb();
  const tables = ['mousePerturb4Tf', 'comp', 'zebraAsdSizes', 'perturbFishAstro'];
  const byGene: Record<string, { table: string; rows: unknown[][]; headers: string[] }[]> = {};

  for (const table of tables) {
    const stmt = db.prepare(
      `SELECT h.symbol as symbol, t.* FROM ${table} as t, hgnc as h WHERE h.hgnc_id=t.hgnc_id`
    );
    const rows: any[] = stmt.all();
    const columns = stmt.columns().map((c) => c.name).slice(1); // drop symbol
    for (const row of rows) {
      const symbol = String(row.symbol);
      const values = columns.map((k) => (row as any)[k]);
      if (!byGene[symbol]) byGene[symbol] = [];
      let entry = byGene[symbol].find((e) => e.table === table);
      if (!entry) {
        entry = { table, rows: [], headers: columns };
        byGene[symbol].push(entry);
      }
      entry.rows.push(values);
    }
  }
  return { data: byGene };
}

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  const db = getDb();
  const page = (req.query.page as string) || undefined;
  const format = (req.query.format as string) || 'json';
  const sortby = (req.query.sortby as string) || undefined;
  const sortorder = (req.query.sortorder as 'asc' | 'desc') || undefined;
  const pageNum = req.query.pageNum ? Number(req.query.pageNum) : undefined;
  const perPage = req.query.perPage ? Number(req.query.perPage) : undefined;

  if (page === 'all') {
    const merged = getMerged();
    return res.status(200).json({ title: 'Integrated assays', ...merged });
  }

  const { sql, title } = queryForPage(page);
  if (!sql) {
    return res.status(400).json({ error: 'Invalid page' });
  }

  const orderBy = buildOrderBy(sortby, sortorder);
  const limit = buildLimit(pageNum, perPage);
  const fullSql = `${sql.replace(/;$/, '')}${orderBy}${limit};`;

  const stmt = db.prepare(fullSql);
  const rows = stmt.all();
  const headers = stmt.columns().map((c) => c.name);

  if (format === 'tsv') {
    const tsvRows = [headers.join('\t')]
      .concat(
        rows.map((r) => headers.map((h) => String((r as any)[h] ?? '')).join('\t'))
      )
      .join('\n');
    res.setHeader('Content-Type', 'text/tab-separated-values');
    res.setHeader('Content-Disposition', 'attachment; filename="geneTable.tsv"');
    return res.status(200).send(tsvRows);
  }

  return res.status(200).json({ title, headers, rows });
}


