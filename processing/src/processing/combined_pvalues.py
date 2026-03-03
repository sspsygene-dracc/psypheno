"""Compute combined p-values per gene across all datasets.

Methods:
- Fisher's method: combines -2*sum(ln(p)) with pre-collapsed per-table p-values
- Stouffer's method: converts to Z-scores with pre-collapsed per-table p-values
- Cauchy combination test (CCT): robust to correlated p-values, uses all raw p-values
- Harmonic mean p-value (HMP): robust to dependency, uses all raw p-values
"""

import csv
import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import click
import numpy as np
from scipy.stats import cauchy as cauchy_dist

from processing.sql_utils import sanitize_identifier
from scipy.stats import combine_pvalues

# HGNC gene_group names mapped to filter flag categories.
# These represent broadly-responsive gene families whose high significance
# in combined p-values typically reflects general perturbation response
# rather than disease-specific signal.
FLAG_GENE_GROUPS: dict[str, list[str]] = {
    "heat_shock": [
        "BAG cochaperones",
        "Chaperonins",
        "DNAJ (HSP40) heat shock proteins",
        "Heat shock 70kDa proteins",
        "Heat shock 90kDa proteins",
        "Small heat shock proteins",
    ],
    "ribosomal": [
        "L ribosomal proteins",
        "S ribosomal proteins",
        "Large subunit mitochondrial ribosomal proteins",
        "Small subunit mitochondrial ribosomal proteins",
        "Mitochondrial ribosomal proteins",
    ],
    "ubiquitin": [
        "Ubiquitin C-terminal hydrolases",
        "Ubiquitin conjugating enzymes E2",
        "Ubiquitin like modifier activating enzymes",
        "Ubiquitin protein ligase E3 component n-recognins",
        "Ubiquitin specific peptidase like",
        "Ubiquitin specific peptidases",
        "Ubiquitins",
    ],
    "mitochondrial_rna": [
        "Mitochondrially encoded long non-coding RNAs",
        "Mitochondrially encoded protein coding genes",
        "Mitochondrially encoded regions",
        "Mitochondrially encoded ribosomal RNAs",
        "Mitochondrially encoded transfer RNAs",
    ],
}

# HGNC locus_group values mapped to filter flag categories.
FLAG_LOCUS_GROUPS: dict[str, list[str]] = {
    "non_coding": ["non-coding RNA"],
}


def _load_hgnc_gene_flags(hgnc_path: Path) -> dict[str, str]:
    """Parse HGNC TSV and return {symbol: comma-separated flags} for flagged genes.

    Uses gene_group to match protein family flags (heat_shock, ribosomal, etc.)
    and locus_group for broader categories (non_coding).
    """
    # Build reverse lookups: group_name -> flag
    group_to_flag: dict[str, str] = {}
    for flag, group_names in FLAG_GENE_GROUPS.items():
        for gn in group_names:
            group_to_flag[gn] = flag

    locus_to_flag: dict[str, str] = {}
    for flag, locus_names in FLAG_LOCUS_GROUPS.items():
        for ln in locus_names:
            locus_to_flag[ln] = flag

    symbol_flags: dict[str, str] = {}
    with open(hgnc_path, "r") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            symbol = row.get("symbol", "").strip()
            if not symbol:
                continue

            flags: set[str] = set()

            # Check gene_group (pipe-separated)
            gene_groups = row.get("gene_group", "")
            if gene_groups:
                for g in gene_groups.split("|"):
                    g = g.strip().strip('"')
                    if g in group_to_flag:
                        flags.add(group_to_flag[g])

            # Check locus_group
            locus_group = row.get("locus_group", "").strip()
            if locus_group in locus_to_flag:
                flags.add(locus_to_flag[locus_group])

            if flags:
                symbol_flags[symbol] = ",".join(sorted(flags))

    return symbol_flags




def _parse_link_tables(link_tables_raw: str) -> list[str]:
    """Extract non-perturbed link table names from data_tables.link_tables.

    Format: "col_name:link_table_name:is_perturbed:is_target,..."

    In tables with both perturbed and target gene mappings, we skip the
    perturbed link table: the perturbed gene appears in every row it was
    knocked down in, so its p-values reflect target effects, not evidence
    about the perturbed gene itself.
    """
    entries = []
    for entry in link_tables_raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        link_table_name = parts[1] if len(parts) >= 2 else parts[0]
        is_perturbed = parts[2] == "1" if len(parts) >= 3 else False
        entries.append((sanitize_identifier(link_table_name), is_perturbed))

    has_perturbed = any(p for _, p in entries)
    has_non_perturbed = any(not p for _, p in entries)

    # If table has both perturbed and non-perturbed mappings, skip perturbed
    if has_perturbed and has_non_perturbed:
        return [name for name, is_perturbed in entries if not is_perturbed]

    # Otherwise keep all (single-mapping tables, or all-perturbed tables)
    return [name for name, _ in entries]


def _cauchy_combination(pvalues: np.ndarray[float, Any]) -> float:
    """Cauchy combination test (CCT).

    Robust to correlated p-values. Uses equal weights.
    Liu & Xie (2020), JASA.
    """
    weights = np.ones(len(pvalues)) / len(pvalues)
    # Clamp extreme p-values to avoid numerical issues with tan
    p_clamped = np.clip(pvalues, 1e-300, 1.0 - 1e-15)
    t_stat = np.sum(weights * np.tan((0.5 - p_clamped) * np.pi))
    combined_p = cauchy_dist.sf(t_stat)
    return float(np.clip(combined_p, 0.0, 1.0))


def _harmonic_mean_pvalue(pvalues: np.ndarray[float, Any]) -> float:
    """Harmonic mean p-value (HMP).

    Wilson (2019), PNAS. Robust to dependency structure.
    Uses equal weights and Landau bound adjustment.
    """
    n = len(pvalues)
    weights = np.ones(n) / n
    # HMP = sum(w) / sum(w/p)
    hmp = np.sum(weights) / np.sum(weights / pvalues)
    # Landau adjustment: multiply by L (number of p-values)
    adjusted = min(float(hmp) * n, 1.0)
    return adjusted


def _benjamini_hochberg(pvalues: list[float | None]) -> list[float | None]:
    """Apply Benjamini-Hochberg FDR correction to a list of p-values.

    None values are preserved as None in the output.
    """
    valid_indices = [i for i, p in enumerate(pvalues) if p is not None]
    if not valid_indices:
        return list(pvalues)

    valid_pvals = np.array([pvalues[i] for i in valid_indices])
    m = len(valid_pvals)

    # Sort by p-value
    sorted_idx = np.argsort(valid_pvals)
    sorted_pvals = valid_pvals[sorted_idx]

    # BH adjustment: q(i) = p(i) * m / rank(i)
    ranks = np.arange(1, m + 1)
    adjusted = sorted_pvals * m / ranks

    # Enforce monotonicity (from largest to smallest)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]

    # Cap at 1.0
    adjusted = np.minimum(adjusted, 1.0)

    # Put back in original order
    unsorted = np.empty(m)
    unsorted[sorted_idx] = adjusted

    result: list[float | None] = [None] * len(pvalues)
    for i, orig_idx in enumerate(valid_indices):
        result[orig_idx] = float(unsorted[i])

    return result


def compute_combined_pvalues(conn: sqlite3.Connection, hgnc_path: Path | None = None) -> None:
    """Compute and store combined p-values per gene across all datasets."""
    click.echo("\nComputing combined p-values...")

    # 1. Find all tables with pvalue_column
    tables_with_pvalues = conn.execute(
        "SELECT table_name, pvalue_column, link_tables FROM data_tables "
        "WHERE pvalue_column IS NOT NULL"
    ).fetchall()

    if not tables_with_pvalues:
        click.echo("  No tables with pvalue_column configured, skipping.")
        return

    # Load HGNC gene flags for classification
    hgnc_flags: dict[str, str] = {}
    if hgnc_path and hgnc_path.exists():
        hgnc_flags = _load_hgnc_gene_flags(hgnc_path)
        click.echo(f"  Loaded HGNC gene flags for {len(hgnc_flags)} genes")

    click.echo(f"  Found {len(tables_with_pvalues)} tables with p-value columns")

    # 2. Collect p-values per gene: {gene_id: {table_name: [pvalues]}}
    per_table_pvalues: dict[int, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # Also collect all raw p-values per gene for CCT/HMP
    all_pvalues: dict[int, list[float]] = defaultdict(list)

    for table_name, pvalue_col, link_tables_raw in tables_with_pvalues:
        table_name = sanitize_identifier(table_name)
        pvalue_col = sanitize_identifier(pvalue_col)
        link_table_names = _parse_link_tables(link_tables_raw or "")

        if not link_table_names:
            continue

        for lt_name in link_table_names:
            query = (
                f"SELECT lt.central_gene_id, t.{pvalue_col} "
                f"FROM {table_name} t "
                f"JOIN {lt_name} lt ON t.id = lt.id "
                f"WHERE t.{pvalue_col} IS NOT NULL AND t.{pvalue_col} > 0 AND t.{pvalue_col} <= 1"
            )
            try:
                rows = conn.execute(query).fetchall()
            except sqlite3.OperationalError as e:
                click.echo(
                    click.style(
                        f"  Warning: query failed for table {table_name}: {e}",
                        fg="yellow",
                    )
                )
                continue

            for gene_id, pval in rows:
                if gene_id is None:
                    continue
                pval_float = float(pval)
                per_table_pvalues[gene_id][table_name].append(pval_float)
                all_pvalues[gene_id].append(pval_float)

        click.echo(f"  Processed {table_name}.{pvalue_col}")

    if not all_pvalues:
        click.echo("  No valid p-values found, skipping.")
        return

    # 3. Compute combined p-values for each gene (collect before inserting)
    gene_results: list[
        tuple[int, float | None, float | None, float | None, float | None, int, int]
    ] = []

    for gene_id in sorted(all_pvalues.keys()):
        raw_pvals = np.array(all_pvalues[gene_id])
        table_dict = per_table_pvalues[gene_id]
        num_tables = len(table_dict)
        num_pvalues = len(raw_pvals)

        # Pre-collapse for Fisher/Stouffer: min(p)*n per table, capped at 1.0
        collapsed_pvals = []
        for _tbl, tbl_pvals in table_dict.items():
            n = len(tbl_pvals)
            collapsed = min(min(tbl_pvals) * n, 1.0)
            collapsed_pvals.append(collapsed)

        # Fisher and Stouffer need >= 2 tables
        fisher_p = None
        stouffer_p = None
        if len(collapsed_pvals) >= 2:
            collapsed_arr = np.array(collapsed_pvals)
            # Filter out p-values of exactly 1.0 (they contribute no information)
            # but keep them if all are 1.0
            valid_collapsed = collapsed_arr[collapsed_arr < 1.0]
            if len(valid_collapsed) >= 2:
                _, fisher_p = cast(
                    tuple[float, float],
                    combine_pvalues(valid_collapsed, method="fisher"),
                )
                fisher_p = float(fisher_p)
                _, stouffer_p = cast(
                    tuple[float, float],
                    combine_pvalues(valid_collapsed, method="stouffer"),
                )
                stouffer_p = float(stouffer_p)

        # CCT and HMP work with any number of p-values >= 1
        cauchy_p = _cauchy_combination(raw_pvals)
        hmp_p = _harmonic_mean_pvalue(raw_pvals)

        # Handle NaN/inf
        if fisher_p is not None and (math.isnan(fisher_p) or math.isinf(fisher_p)):
            fisher_p = None
        if stouffer_p is not None and (
            math.isnan(stouffer_p) or math.isinf(stouffer_p)
        ):
            stouffer_p = None
        if math.isnan(cauchy_p) or math.isinf(cauchy_p):
            cauchy_p = None
        if math.isnan(hmp_p) or math.isinf(hmp_p):
            hmp_p = None

        gene_results.append(
            (gene_id, fisher_p, stouffer_p, cauchy_p, hmp_p, num_tables, num_pvalues)
        )

    # 4. Apply Benjamini-Hochberg FDR correction across all genes per method
    fisher_fdrs = _benjamini_hochberg([r[1] for r in gene_results])
    stouffer_fdrs = _benjamini_hochberg([r[2] for r in gene_results])
    cauchy_fdrs = _benjamini_hochberg([r[3] for r in gene_results])
    hmp_fdrs = _benjamini_hochberg([r[4] for r in gene_results])

    # 5. Build symbol lookup for gene flags
    symbol_lookup: dict[int, str] = {}
    if hgnc_flags:
        rows_sym = conn.execute(
            "SELECT id, human_symbol FROM central_gene WHERE human_symbol IS NOT NULL"
        ).fetchall()
        symbol_lookup = {row[0]: row[1] for row in rows_sym}

    # 6. Create output table and insert
    conn.execute(
        """CREATE TABLE gene_combined_pvalues (
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

    for i, (gene_id, fisher_p, stouffer_p, cauchy_p, hmp_p, n_tbl, n_pv) in enumerate(
        gene_results
    ):
        # Look up gene flags from HGNC
        gene_flag = None
        if hgnc_flags:
            symbol = symbol_lookup.get(gene_id)
            if symbol:
                gene_flag = hgnc_flags.get(symbol)

        conn.execute(
            """INSERT INTO gene_combined_pvalues
            (central_gene_id, fisher_pvalue, fisher_fdr, stouffer_pvalue, stouffer_fdr,
             cauchy_pvalue, cauchy_fdr, hmp_pvalue, hmp_fdr, num_tables, num_pvalues,
             gene_flags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                gene_id,
                fisher_p,
                fisher_fdrs[i],
                stouffer_p,
                stouffer_fdrs[i],
                cauchy_p,
                cauchy_fdrs[i],
                hmp_p,
                hmp_fdrs[i],
                n_tbl,
                n_pv,
                gene_flag,
            ),
        )

    conn.execute(
        "CREATE INDEX gene_combined_pvalues_gene_idx "
        "ON gene_combined_pvalues (central_gene_id)"
    )
    conn.commit()

    click.echo(
        f"  Computed combined p-values for "
        f"{click.style(str(len(gene_results)), bold=True)} genes"
    )
