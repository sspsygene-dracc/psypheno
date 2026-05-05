"""P-value collection from SQLite + the small pure helpers it depends on.

`collect_pvalues_for_tables` is the SQL-heavy stage; `filter_collected`
re-uses a master scan to derive each filtered group's CollectedPvalues.
`parse_link_tables_for_direction` and `precollapse` are pure helpers
shared by collection and the R writer.
"""

import sqlite3

import click

from processing.sql_utils import sanitize_identifier

from .data import CollectedPvalues, Regulation, SourceTableQuad


def parse_link_tables_for_direction(link_tables_raw: str, direction: str) -> list[str]:
    """Extract link tables matching a specific search direction.

    direction must be "target" or "perturbed".

    Format: "col_name:link_table_name:direction" (direction is the literal
    string "perturbed" or "target"). Each link-table entry has exactly one
    direction; we keep only the entries whose direction matches the request.
    """
    if direction not in ("target", "perturbed"):
        raise ValueError(
            f"direction must be 'target' or 'perturbed', got {direction!r}"
        )
    out: list[str] = []
    for entry in link_tables_raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 3:
            continue
        link_table_name = parts[1]
        entry_direction = parts[2]
        if entry_direction == direction:
            out.append(sanitize_identifier(link_table_name))
    return out


def precollapse(pvalues: list[float]) -> float:
    """Bonferroni pre-collapse: min(p) * n, capped at 1.0.

    Native float is sufficient: `n` is bounded by the rows of one source
    table (always small), and the smallest realistic p-value sits well
    above the IEEE 754 normal range, so the multiply cannot under/overflow.
    """
    return min(min(pvalues) * len(pvalues), 1.0)


def collect_pvalues_for_tables(
    conn: sqlite3.Connection,
    tables_with_pvalues: list[SourceTableQuad],
    label: str = "",
    direction: str = "target",
    regulation: Regulation = "any",
) -> CollectedPvalues:
    """Collect p-values from the database for the given tables.

    direction must be "target" or "perturbed"; tables whose link-table entries
    don't include the matching direction are silently skipped.

    regulation:
      - "any" — collect every row that passes the standard filters (current
        default behavior).
      - "up" / "down" — restrict to rows whose table-declared effect_column is
        > 0 (up) or < 0 (down). Tables without an effect_column are skipped
        entirely under up/down (since signed direction is undefined for them).
    """
    collected = CollectedPvalues()

    for table_name, pvalue_cols_raw, link_tables_raw, effect_col_raw in (
        tables_with_pvalues
    ):
        table_name = sanitize_identifier(table_name)
        pvalue_cols = [sanitize_identifier(c) for c in pvalue_cols_raw.split(",")]
        link_table_names = parse_link_tables_for_direction(
            link_tables_raw or "", direction
        )

        if not link_table_names:
            continue

        # Up/down regulation requires the table to declare an effect_column.
        if regulation != "any" and not effect_col_raw:
            continue
        effect_col = (
            sanitize_identifier(effect_col_raw) if effect_col_raw else None
        )
        sign_clause = ""
        if regulation == "up" and effect_col is not None:
            sign_clause = f" AND t.{effect_col} > 0"
        elif regulation == "down" and effect_col is not None:
            sign_clause = f" AND t.{effect_col} < 0"

        for pvalue_col in pvalue_cols:
            for lt_name in link_table_names:
                # Exclude rows linked to a kind='control' central_gene
                # (NonTarget1, SafeTarget, GFP, …). Without this, the
                # combined-p meta-analysis would compute a "p-value for
                # NonTarget1" — meaningless, since controls aren't being
                # tested for an effect. See discussion #19.
                query = (
                    f"SELECT lt.central_gene_id, t.{pvalue_col} "
                    f"FROM {table_name} t "
                    f"JOIN {lt_name} lt ON t.id = lt.id "
                    f"JOIN central_gene cg ON cg.id = lt.central_gene_id "
                    f"WHERE t.{pvalue_col} IS NOT NULL "
                    f"AND t.{pvalue_col} > 0 AND t.{pvalue_col} <= 1 "
                    f"AND cg.kind = 'gene'"
                    f"{sign_clause}"
                )
                try:
                    rows = conn.execute(query).fetchall()
                except sqlite3.OperationalError as e:
                    click.echo(
                        click.style(
                            f"  Warning: query failed for table "
                            f"{table_name}.{pvalue_col}: {e}",
                            fg="yellow",
                        )
                    )
                    continue

                for gene_id, pval in rows:
                    if gene_id is None:
                        continue
                    pval_float = float(pval)
                    collected.per_table[gene_id][table_name].append(pval_float)
                    collected.all_pvalues[gene_id].append(pval_float)

        col_label = ", ".join(pvalue_cols) if len(pvalue_cols) > 1 else pvalue_cols[0]
        click.echo(f"  {label}Processed {table_name}.{col_label}")

    return collected


def filter_collected(
    master: CollectedPvalues, table_names: set[str]
) -> CollectedPvalues:
    """Restrict master to per_table entries whose table_name is in table_names,
    rebuilding all_pvalues from the surviving per_table entries."""
    out = CollectedPvalues()
    for gene_id, tbl_dict in master.per_table.items():
        for tbl, pvals in tbl_dict.items():
            if tbl in table_names:
                out.per_table[gene_id][tbl] = list(pvals)
                out.all_pvalues[gene_id].extend(pvals)
    return out
