import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { getDb } from '../../lib/db';

type PageProps =
  | {
      page: 'all';
      merged: Record<string, { table: string; rows: unknown[][]; headers: string[] }[]>;
    }
  | {
      page: string;
      title: string;
      headers: string[];
      rows: Record<string, unknown>[];
    };

export default function PhenoPage(props: PageProps) {
  const isAll = (p: PageProps): p is Extract<PageProps, { page: 'all' }> => p.page === 'all';

  if (isAll(props)) {
    const entries = Object.entries(props.merged) as [
      string,
      { table: string; rows: unknown[][]; headers: string[] }[]
    ][];
    return (
      <div style={{ padding: 12 }}>
        <p>
          <Link href="/pheno">Back</Link>
        </p>
        <h4>Integrated assays</h4>
        <div>
          {entries.map(([symbol, tables]: [
            string,
            { table: string; rows: unknown[][]; headers: string[] }[]
          ]) => (
            <div key={symbol} style={{ marginBottom: 24 }}>
              <h3 id={symbol}>{symbol}</h3>
              {tables.map((t: { table: string; rows: unknown[][]; headers: string[] }) => (
                <div key={t.table} style={{ marginBottom: 12 }}>
                  <h4>{t.table}</h4>
                  <table className="pure-table">
                    <thead>
                      <tr>
                        {t.headers
                          .filter((h: string) => h !== 'hgnc_id')
                          .map((h: string) => (
                            <th key={h}>{h}</th>
                          ))}
                      </tr>
                    </thead>
                    <tbody>
                      {t.rows.map((row: unknown[], idx: number) => (
                        <tr key={idx}>
                          {t.headers
                            .filter((h: string) => h !== 'hgnc_id')
                            .map((_: string, i: number) => (
                              <td key={i}>{String((row as any)[i] ?? '')}</td>
                            ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    );
  }

  const { page, title, headers, rows } = props as Extract<
    PageProps,
    { page: string; title: string; headers: string[]; rows: Record<string, unknown>[] }
  >;
  return (
    <div style={{ padding: 12 }}>
      <p>
        <Link href="/pheno">Back</Link>
      </p>
      <h4>{title}</h4>
      <p>
        <a href={`/api/pheno?page=${encodeURIComponent(page)}&format=tsv`}>
          Download TSV
        </a>
      </p>
      <table className="pure-table" style={{ tableLayout: 'fixed', width: '100%' }}>
        <thead>
          <tr>
            {headers.map((h: string) => (
              <th key={h}>{h.replaceAll('_', ' ')}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r: Record<string, unknown>, idx: number) => (
            <tr key={idx}>
              {headers.map((h: string) => (
                <td key={h}>{String((r as any)[h] ?? '')}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const getServerSideProps: GetServerSideProps<PageProps> = async (ctx) => {
  const page = String(ctx.params?.page || '');
  const db = getDb();

  if (page === 'all') {
    const tables = ['mousePerturb4Tf', 'comp', 'zebraAsdSizes', 'perturbFishAstro'];
    const merged: Record<string, { table: string; rows: unknown[][]; headers: string[] }[]> = {};
    for (const table of tables) {
      const stmt = db.prepare(
        `SELECT h.symbol as symbol, t.* FROM ${table} as t, hgnc as h WHERE h.hgnc_id=t.hgnc_id`
      );
      const rows: any[] = stmt.all();
      const cols = stmt.columns().map((c) => c.name).slice(1);
      for (const row of rows) {
        const symbol = String(row.symbol);
        const vals = cols.map((k) => (row as any)[k]);
        if (!merged[symbol]) merged[symbol] = [];
        let entry = merged[symbol].find((e) => e.table === table);
        if (!entry) {
          entry = { table, rows: [], headers: cols };
          merged[symbol].push(entry);
        }
        entry.rows.push(vals);
      }
    }
    return { props: { page: 'all', merged } };
  }

  let sql: string | null = null;
  let title = 'Phenotypes';
  switch (page) {
    case 'deg':
      sql =
        'select hgnc.symbol, m.gene, m.cellType, m.logFC, m.PValue, m.perturbation, m.target from mousePerturb4Tf as m, hgnc where hgnc.hgnc_id=m.hgnc_id order by perturbation;';
      title = 'Gene expression changes';
      break;
    case 'comp':
      sql = 'SELECT symbol, subcluster, PropRatio, FDR FROM comp, hgnc where comp.hgnc_id=hgnc.hgnc_id;';
      title = 'Cell type composition changes';
      break;
    case 'sizes':
      sql =
        'select symbol, Forebrain, Optic_Tectum, Thalamus, Hypothalamus, Cerebellum, Hindbrain, Habenula, Posterior_Tuberculum,Mutant_Experiment_Sample from zebraAsdSizes as z, hgnc where hgnc.hgnc_id=z.hgnc_id;';
      title = 'Zebrafish brain region sizes';
      break;
    case 'perturbFishAstr':
      sql =
        'SELECT symbol, gene, LFC, qVal from perturbFishAstro as p, hgnc where hgnc.hgnc_id=p.hgnc_id;';
      title = 'Perturb-fish expression changes';
      break;
  }

  if (!sql) {
    return { notFound: true };
  }

  const stmt = db.prepare(sql);
  const rows: any[] = stmt.all();
  const headers = stmt.columns().map((c) => c.name);

  return { props: { page, title, headers, rows } };
};



