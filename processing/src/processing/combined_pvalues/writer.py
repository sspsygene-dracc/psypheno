"""Result-table writing for the combined-p-values pipeline."""

import sqlite3
from collections.abc import Callable

import click

from processing.sql_utils import sanitize_identifier

from .data import CollectedPvalues, GeneCombinedPvalues


def write_combined_results(
    conn: sqlite3.Connection,
    output_table: str,
    pvalues: CollectedPvalues,
    r_results: dict[int, GeneCombinedPvalues],
    no_index: bool,
    gene_flags_fn: Callable[[int], str | None] | None = None,
    label: str = "",
) -> None:
    """Create the output table and insert combined p-value results."""
    out_table = sanitize_identifier(output_table)
    conn.execute(
        f"""CREATE TABLE {out_table} (
        central_gene_id INTEGER PRIMARY KEY,
        fisher_pvalue REAL,
        fisher_fdr REAL,
        stouffer_pvalue REAL,
        stouffer_fdr REAL,
        cauchy_pvalue REAL,
        cauchy_fdr REAL,
        hmp_pvalue REAL,
        hmp_fdr REAL,
        num_tables INTEGER,
        num_pvalues INTEGER,
        gene_flags TEXT
        )"""
    )

    for gene_id in sorted(pvalues.all_pvalues.keys()):
        num_tables = len(pvalues.per_table[gene_id])
        num_pvalues = len(pvalues.all_pvalues[gene_id])
        r = r_results.get(gene_id)
        gene_flag = gene_flags_fn(gene_id) if gene_flags_fn else None

        conn.execute(
            f"""INSERT INTO {out_table}
            (central_gene_id, fisher_pvalue, fisher_fdr, stouffer_pvalue,
             stouffer_fdr, cauchy_pvalue, cauchy_fdr, hmp_pvalue, hmp_fdr,
             num_tables, num_pvalues, gene_flags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                gene_id,
                r.fisher_p if r else None,
                r.fisher_fdr if r else None,
                r.stouffer_p if r else None,
                r.stouffer_fdr if r else None,
                r.cauchy_p if r else None,
                r.cauchy_fdr if r else None,
                r.hmp_p if r else None,
                r.hmp_fdr if r else None,
                num_tables,
                num_pvalues,
                gene_flag,
            ),
        )

    if not no_index:
        conn.execute(
            f"CREATE INDEX {out_table}_gene_idx "
            f"ON {out_table} (central_gene_id)"
        )
    conn.commit()

    n_with_results = len(r_results)
    if n_with_results > 0:
        click.echo(
            f"  {label}Computed combined p-values for "
            f"{click.style(str(n_with_results), bold=True)} genes"
        )
    else:
        click.echo(f"  {label}No combined p-value results (R may be unavailable)")
