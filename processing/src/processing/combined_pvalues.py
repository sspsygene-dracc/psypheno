"""Compute combined p-values per gene across all datasets.

Statistical computation is delegated to R via subprocess, using reference
implementations from the STAAR, harmonicmeanp, and base R packages.
Python handles data collection from SQLite, pre-collapse, HGNC gene flags,
and writing results back to SQLite.

Methods:
- Fisher's method: combines -2*sum(ln(p)) with pre-collapsed per-table p-values
- Stouffer's method: converts to Z-scores with pre-collapsed per-table p-values
- Cauchy combination test (CCT): robust to correlated p-values, uses all raw p-values
- Harmonic mean p-value (HMP): Landau-calibrated, robust to dependency, all raw p-values
"""

import csv
import math
import shutil
import sqlite3
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

import click
import mpmath

from processing.sql_utils import sanitize_identifier

# Path to the R script that computes combined p-values
_R_SCRIPT = Path(__file__).parent / "r" / "compute_combined.R"

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
    "pseudogene": ["pseudogene"],
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


def _precollapse(pvalues: list[float]) -> float:
    """Bonferroni pre-collapse: min(p) * n, capped at 1.0.

    Uses mpmath for arbitrary-precision arithmetic to avoid precision loss
    when p-values are very small (e.g., min(p) = 1e-300 with n = 5).
    """
    n = len(pvalues)
    min_p = mpmath.mpf(min(pvalues))
    collapsed = min_p * n
    return float(min(collapsed, mpmath.mpf(1)))


def _ensure_r_packages(rscript: str) -> bool:
    """Check for required R packages; attempt to install if missing.

    Returns True if all packages are available, False otherwise.
    """
    check = subprocess.run(
        [rscript, "-e", 'library(harmonicmeanp)'],
        capture_output=True, text=True, timeout=30,
    )
    if check.returncode == 0:
        return True

    click.echo("  Attempting to install missing R packages (harmonicmeanp)...")
    install = subprocess.run(
        [rscript, "-e",
         'install.packages("harmonicmeanp", repos="https://cloud.r-project.org", quiet=TRUE)'],
        capture_output=True, text=True, timeout=300,
    )
    if install.returncode != 0:
        click.echo(click.style(
            f"  Failed to install R packages:\n{install.stderr.strip()}",
            fg="yellow", bold=True,
        ))
        return False

    # Verify after install
    verify = subprocess.run(
        [rscript, "-e", 'library(harmonicmeanp)'],
        capture_output=True, text=True, timeout=30,
    )
    return verify.returncode == 0


def _call_r_combine(
    per_table_pvalues: dict[int, dict[str, list[float]]],
    all_pvalues: dict[int, list[float]],
) -> dict[int, dict[str, float | None]] | None:
    """Call R to compute combined p-values and FDR corrections.

    Writes input CSVs, invokes Rscript, reads result CSV.
    Returns {gene_id: {fisher_p, stouffer_p, cauchy_p, hmp_p,
                       fisher_fdr, stouffer_fdr, cauchy_fdr, hmp_fdr}},
    or None if R is unavailable.
    """
    rscript = shutil.which("Rscript")
    if rscript is None:
        click.echo(click.style(
            "\n  WARNING: Rscript not found on PATH. "
            "Combined p-values will not be computed.\n"
            "  Install R to enable this feature: brew install r (macOS) "
            "or apt install r-base (Ubuntu)\n",
            fg="yellow", bold=True,
        ))
        return None

    if not _ensure_r_packages(rscript):
        click.echo(click.style(
            "\n  WARNING: Required R packages could not be installed. "
            "Combined p-values will not be computed.\n",
            fg="yellow", bold=True,
        ))
        return None

    if not _R_SCRIPT.exists():
        click.echo(click.style(
            f"\n  WARNING: R script not found: {_R_SCRIPT}. "
            "Combined p-values will not be computed.\n",
            fg="yellow", bold=True,
        ))
        return None

    tmp_dir = tempfile.mkdtemp(prefix="sspsygene_combine_")
    try:
        # Write collapsed p-values (one row per gene-table pair)
        collapsed_path = Path(tmp_dir) / "collapsed_pvalues.csv"
        with open(collapsed_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["gene_id", "pvalue"])
            for gene_id in sorted(per_table_pvalues.keys()):
                table_dict = per_table_pvalues[gene_id]
                for tbl_pvals in table_dict.values():
                    collapsed = _precollapse(tbl_pvals)
                    writer.writerow([gene_id, f"{collapsed:.17e}"])

        # Write raw p-values (one row per raw p-value)
        raw_path = Path(tmp_dir) / "raw_pvalues.csv"
        with open(raw_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["gene_id", "pvalue"])
            for gene_id in sorted(all_pvalues.keys()):
                for pval in all_pvalues[gene_id]:
                    writer.writerow([gene_id, f"{pval:.17e}"])

        # Call R
        result = subprocess.run(
            [rscript, str(_R_SCRIPT), tmp_dir],
            capture_output=True,
            text=True,
            timeout=600,
        )

        # Print R's stdout (progress messages)
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                click.echo(line)

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(
                f"R script failed (exit code {result.returncode}):\n{stderr}"
            )

        # Read results
        results_path = Path(tmp_dir) / "results.csv"
        if not results_path.exists():
            raise RuntimeError(f"R script did not produce {results_path}")

        gene_results: dict[int, dict[str, float | None]] = {}
        with open(results_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                gene_id = int(row["gene_id"])
                gene_results[gene_id] = {}
                for key in [
                    "fisher_p", "stouffer_p", "cauchy_p", "hmp_p",
                    "fisher_fdr", "stouffer_fdr", "cauchy_fdr", "hmp_fdr",
                ]:
                    val_str = row[key]
                    if val_str in ("NA", "", "NaN", "Inf", "-Inf"):
                        gene_results[gene_id][key] = None
                    else:
                        val = float(val_str)
                        if math.isnan(val) or math.isinf(val):
                            gene_results[gene_id][key] = None
                        else:
                            gene_results[gene_id][key] = val

        return gene_results

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def compute_combined_pvalues(
    conn: sqlite3.Connection,
    hgnc_path: Path | None = None,
    no_index: bool = False,
) -> None:
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

    # 3. Call R for statistical computation
    click.echo("  Calling R for p-value combination and FDR correction...")
    r_results = _call_r_combine(per_table_pvalues, all_pvalues)
    if r_results is None:
        # R unavailable — create empty table so the rest of the page still works
        r_results = {}

    # 4. Build symbol lookup for gene flags and HGNC annotation status
    symbol_lookup: dict[int, str] = {}
    hgnc_id_lookup: dict[int, str | None] = {}
    rows_gene = conn.execute(
        "SELECT id, human_symbol, hgnc_id FROM central_gene WHERE human_symbol IS NOT NULL"
    ).fetchall()
    for row in rows_gene:
        symbol_lookup[row[0]] = row[1]
        hgnc_id_lookup[row[0]] = row[2]

    # 5. Create output table and insert
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

    for gene_id in sorted(all_pvalues.keys()):
        num_tables = len(per_table_pvalues[gene_id])
        num_pvalues = len(all_pvalues[gene_id])

        # Get R results for this gene
        r = r_results.get(gene_id, {})

        # Look up gene flags from HGNC
        flags: set[str] = set()
        symbol = symbol_lookup.get(gene_id)
        if symbol and hgnc_flags:
            flag_str = hgnc_flags.get(symbol)
            if flag_str:
                flags.update(flag_str.split(","))

        # Flag genes without HGNC annotation
        hgnc_id = hgnc_id_lookup.get(gene_id)
        if not hgnc_id:
            flags.add("no_hgnc")

        gene_flag = ",".join(sorted(flags)) if flags else None

        conn.execute(
            """INSERT INTO gene_combined_pvalues
            (central_gene_id, fisher_pvalue, fisher_fdr, stouffer_pvalue, stouffer_fdr,
             cauchy_pvalue, cauchy_fdr, hmp_pvalue, hmp_fdr, num_tables, num_pvalues,
             gene_flags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                gene_id,
                r.get("fisher_p"),
                r.get("fisher_fdr"),
                r.get("stouffer_p"),
                r.get("stouffer_fdr"),
                r.get("cauchy_p"),
                r.get("cauchy_fdr"),
                r.get("hmp_p"),
                r.get("hmp_fdr"),
                num_tables,
                num_pvalues,
                gene_flag,
            ),
        )

    if not no_index:
        conn.execute(
            "CREATE INDEX gene_combined_pvalues_gene_idx "
            "ON gene_combined_pvalues (central_gene_id)"
        )
    conn.commit()

    n_with_results = sum(1 for r in r_results.values() if r)
    if n_with_results > 0:
        click.echo(
            f"  Computed combined p-values for "
            f"{click.style(str(n_with_results), bold=True)} genes"
        )
    else:
        click.echo("  No combined p-value results (R may be unavailable)")
