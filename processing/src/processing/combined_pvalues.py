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
import os
import shutil
import sqlite3
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import mpmath

from processing.sql_utils import sanitize_identifier


@dataclass
class CollectedPvalues:
    """P-values gathered for one compute group, keyed by central_gene_id.

    `per_table` keeps p-values bucketed by source table so the per-gene
    Bonferroni pre-collapse can run per-table; `all_pvalues` is the flat
    list used by methods (Cauchy, HMP) that consume raw p-values directly.
    """

    per_table: defaultdict[int, defaultdict[str, list[float]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list))
    )
    all_pvalues: defaultdict[int, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def is_empty(self) -> bool:
        return not self.all_pvalues

    @classmethod
    def from_dicts(
        cls,
        per_table: dict[int, dict[str, list[float]]],
        all_pvalues: dict[int, list[float]],
    ) -> "CollectedPvalues":
        """Build a CollectedPvalues from plain nested dicts (test convenience)."""
        out = cls()
        for gid, tbl_dict in per_table.items():
            for tbl, pvals in tbl_dict.items():
                out.per_table[gid][tbl] = list(pvals)
        for gid, pvals in all_pvalues.items():
            out.all_pvalues[gid] = list(pvals)
        return out


@dataclass
class GeneCombinedPvalues:
    """Combined-p-value record for one gene as returned by the R script."""

    fisher_p: float | None
    fisher_fdr: float | None
    stouffer_p: float | None
    stouffer_fdr: float | None
    cauchy_p: float | None
    cauchy_fdr: float | None
    hmp_p: float | None
    hmp_fdr: float | None


@dataclass
class ComputeGroup:
    """Spec for one pre-computed combined-p-values output table.

    `direction` is None for legacy groups (drop perturbed only when a single
    table has both sides) and "target" / "perturbed" for the direction-aware
    groups that drive the gene-search flip toggle.
    """

    tables: list[tuple[str, str, str]]
    out_table: str
    label: str
    assay_filter: str | None = None
    disease_filter: str | None = None
    use_gene_flags: bool = True
    min_tables: int = 1
    direction: str | None = None


@dataclass
class CollectedGroup:
    """A ComputeGroup paired with its collected p-values, ready for R."""

    pvalues: CollectedPvalues
    out_table: str
    label: str
    assay_filter: str | None
    disease_filter: str | None
    use_gene_flags: bool


@dataclass
class RJobInput:
    """Input to one R meta-analysis job submitted to the thread pool."""

    idx: int
    pvalues: CollectedPvalues
    label: str

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


def _load_tf_list(tf_list_path: Path) -> set[str]:
    """Load HGNC symbols of confirmed transcription factors from CisBP DatabaseExtract CSV."""
    tf_symbols: set[str] = set()
    with open(tf_list_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Is TF?", "").strip() == "Yes":
                symbol = row.get("HGNC symbol", "").strip()
                if symbol:
                    tf_symbols.add(symbol)
    return tf_symbols


def _load_hgnc_gene_flags(
    hgnc_path: Path, tf_symbols: set[str] | None = None
) -> dict[str, str]:
    """Parse HGNC TSV and return {symbol: comma-separated flags} for flagged genes.

    Uses gene_group to match protein family flags (heat_shock, ribosomal, etc.),
    locus_group for broader categories (non_coding), tf_symbols set for
    transcription factors, and locus_type for lncRNAs.
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
            # Check transcription factor list
            if tf_symbols and symbol in tf_symbols:
                flags.add("transcription_factor")

            # Check locus_group
            locus_group = row.get("locus_group", "").strip()
            if locus_group in locus_to_flag:
                flags.add(locus_to_flag[locus_group])

            # Check locus_type for lncRNAs
            locus_type = row.get("locus_type", "").strip()
            if locus_type == "RNA, long non-coding":
                flags.add("lncrna")

            if flags:
                symbol_flags[symbol] = ",".join(sorted(flags))

    return symbol_flags


def _load_nimh_priority_genes(nimh_csv_path: Path) -> set[str]:
    """Load NIMH priority gene symbols from CSV, returning a deduplicated set."""
    symbols: set[str] = set()
    with open(nimh_csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row.get("gene_symbol", "").strip()
            if symbol:
                symbols.add(symbol)
    return symbols


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


def _parse_link_tables_for_direction(
    link_tables_raw: str, direction: str
) -> list[str]:
    """Extract link tables for a specific search direction.

    direction must be "target" or "perturbed".

    Selection rule per link-table entry "col:lt:is_perturbed:is_target":
      target    -> include if is_target == 1 OR (both flags 0)
      perturbed -> include if is_perturbed == 1 OR (both flags 0)

    Generic gene tables (both flags 0, e.g. SFARI/MGI) appear in both
    directions. Pure-target tables only appear in target mode; pure-perturbed
    tables only appear in perturbed mode. Mixed-direction tables contribute
    only the matching side.
    """
    if direction not in ("target", "perturbed"):
        raise ValueError(f"direction must be 'target' or 'perturbed', got {direction!r}")
    out: list[str] = []
    for entry in link_tables_raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        link_table_name = parts[1] if len(parts) >= 2 else parts[0]
        is_perturbed = parts[2] == "1" if len(parts) >= 3 else False
        is_target = parts[3] == "1" if len(parts) >= 4 else False
        is_generic = (not is_perturbed) and (not is_target)
        keep = (
            (direction == "target" and (is_target or is_generic))
            or (direction == "perturbed" and (is_perturbed or is_generic))
        )
        if keep:
            out.append(sanitize_identifier(link_table_name))
    return out


def _precollapse(pvalues: list[float]) -> float:
    """Bonferroni pre-collapse: min(p) * n, capped at 1.0.

    Uses mpmath for arbitrary-precision arithmetic to avoid precision loss
    when p-values are very small (e.g., min(p) = 1e-300 with n = 5).
    """
    n = len(pvalues)
    min_p = mpmath.mpf(min(pvalues))
    collapsed = min_p * n
    return float(min(collapsed, mpmath.mpf(1)))


_REQUIRED_R_PACKAGES = ["poolr", "ACAT", "harmonicmeanp"]

# User-local R library, used when the system library is not writable
_R_USER_LIB = Path(__file__).parent / "r" / "lib"


def _r_lib_setup_code() -> str:
    """R code to prepend our user library to .libPaths()."""
    lib_path = str(_R_USER_LIB).replace("\\", "/")
    return f'dir.create("{lib_path}", recursive=TRUE, showWarnings=FALSE); .libPaths(c("{lib_path}", .libPaths()))'


def _ensure_r_packages(rscript: str) -> bool:
    """Check for required R packages; attempt to install if missing.

    Returns True if all packages are available, False otherwise.
    Uses a project-local R library to avoid requiring write access
    to the system R library.
    """
    setup = _r_lib_setup_code()
    check_code = setup + "; " + "; ".join(f"library({pkg})" for pkg in _REQUIRED_R_PACKAGES)
    check = subprocess.run(
        [rscript, "-e", check_code],
        capture_output=True, text=True, timeout=30,
    )
    if check.returncode == 0:
        return True

    lib_path = str(_R_USER_LIB).replace("\\", "/")

    # Try to install missing CRAN packages
    cran_pkgs = [p for p in _REQUIRED_R_PACKAGES if p != "ACAT"]
    if cran_pkgs:
        pkg_list = ", ".join(f'"{p}"' for p in cran_pkgs)
        click.echo(f"  Attempting to install missing R packages ({', '.join(cran_pkgs)})...")
        install = subprocess.run(
            [rscript, "-e",
             f'{setup}; install.packages(c({pkg_list}), lib="{lib_path}", '
             f'repos="https://cloud.r-project.org", quiet=TRUE)'],
            capture_output=True, text=True, timeout=300,
        )
        if install.returncode != 0:
            click.echo(click.style(
                f"  Failed to install CRAN packages:\n{install.stderr.strip()}",
                fg="yellow", bold=True,
            ))

    # ACAT is not on CRAN; install from GitHub via remotes
    acat_check = subprocess.run(
        [rscript, "-e", f'{setup}; library(ACAT)'],
        capture_output=True, text=True, timeout=30,
    )
    if acat_check.returncode != 0:
        click.echo("  Attempting to install ACAT from GitHub...")
        acat_install = subprocess.run(
            [rscript, "-e",
             f'{setup}; '
             f'if (!requireNamespace("remotes", quietly=TRUE)) '
             f'install.packages("remotes", lib="{lib_path}", '
             f'repos="https://cloud.r-project.org", quiet=TRUE); '
             f'remotes::install_github("yaowuliu/ACAT", lib="{lib_path}", quiet=TRUE)'],
            capture_output=True, text=True, timeout=300,
        )
        if acat_install.returncode != 0:
            click.echo(click.style(
                f"  Failed to install ACAT:\n{acat_install.stderr.strip()}",
                fg="yellow", bold=True,
            ))

    # Verify all packages
    verify = subprocess.run(
        [rscript, "-e", check_code],
        capture_output=True, text=True, timeout=30,
    )
    if verify.returncode != 0:
        click.echo(click.style(
            "\n  WARNING: Required R packages could not be installed. "
            "Combined p-values will not be computed.\n",
            fg="yellow", bold=True,
        ))
        return False
    return True


def _call_r_combine(
    pvalues: CollectedPvalues,
) -> dict[int, GeneCombinedPvalues] | None:
    """Call R to compute combined p-values and FDR corrections.

    Writes input CSVs, invokes Rscript, reads result CSV. Returns the
    per-gene combined p-values, or None if R is unavailable.
    """
    per_table_pvalues = pvalues.per_table
    all_pvalues = pvalues.all_pvalues
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

        def _parse_cell(val_str: str) -> float | None:
            if val_str in ("NA", "", "NaN", "Inf", "-Inf"):
                return None
            val = float(val_str)
            if math.isnan(val) or math.isinf(val):
                return None
            return val

        gene_results: dict[int, GeneCombinedPvalues] = {}
        with open(results_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                gene_id = int(row["gene_id"])
                gene_results[gene_id] = GeneCombinedPvalues(
                    fisher_p=_parse_cell(row["fisher_p"]),
                    fisher_fdr=_parse_cell(row["fisher_fdr"]),
                    stouffer_p=_parse_cell(row["stouffer_p"]),
                    stouffer_fdr=_parse_cell(row["stouffer_fdr"]),
                    cauchy_p=_parse_cell(row["cauchy_p"]),
                    cauchy_fdr=_parse_cell(row["cauchy_fdr"]),
                    hmp_p=_parse_cell(row["hmp_p"]),
                    hmp_fdr=_parse_cell(row["hmp_fdr"]),
                )

        return gene_results

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _collect_pvalues_for_tables(
    conn: sqlite3.Connection,
    tables_with_pvalues: list[tuple[str, str, str]],
    label: str = "",
    direction: str | None = None,
) -> CollectedPvalues:
    """Collect p-values from the database for the given tables.

    direction: if "target" or "perturbed", uses _parse_link_tables_for_direction;
    if None, uses the legacy _parse_link_tables (drop perturbed only when both
    sides exist in the same table).
    """
    collected = CollectedPvalues()

    for table_name, pvalue_cols_raw, link_tables_raw in tables_with_pvalues:
        table_name = sanitize_identifier(table_name)
        pvalue_cols = [sanitize_identifier(c) for c in pvalue_cols_raw.split(",")]
        if direction is None:
            link_table_names = _parse_link_tables(link_tables_raw or "")
        else:
            link_table_names = _parse_link_tables_for_direction(
                link_tables_raw or "", direction
            )

        if not link_table_names:
            continue

        for pvalue_col in pvalue_cols:
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
                            f"  Warning: query failed for table {table_name}.{pvalue_col}: {e}",
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


def _write_combined_results(
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
            (central_gene_id, fisher_pvalue, fisher_fdr, stouffer_pvalue, stouffer_fdr,
             cauchy_pvalue, cauchy_fdr, hmp_pvalue, hmp_fdr, num_tables, num_pvalues,
             gene_flags)
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


def compute_combined_pvalues(
    conn: sqlite3.Connection,
    hgnc_path: Path | None = None,
    no_index: bool = False,
    nimh_csv_path: Path | None = None,
    tf_list_path: Path | None = None,
) -> None:
    """Compute and store combined p-values per gene across all datasets,
    then separately per assay type."""
    click.echo("\nComputing combined p-values...")

    # 1. Find all tables with pvalue_column (include assay and disease for splits)
    tables_with_pvalues = conn.execute(
        "SELECT table_name, pvalue_column, link_tables, assay, disease FROM data_tables "
        "WHERE pvalue_column IS NOT NULL"
    ).fetchall()

    if not tables_with_pvalues:
        click.echo("  No tables with pvalue_column configured, skipping.")
        return

    # Load transcription factor list
    tf_symbols: set[str] | None = None
    if tf_list_path and tf_list_path.exists():
        tf_symbols = _load_tf_list(tf_list_path)
        click.echo(f"  Loaded TF list: {len(tf_symbols)} transcription factors")

    # Load HGNC gene flags for classification
    hgnc_flags: dict[str, str] = {}
    if hgnc_path and hgnc_path.exists():
        hgnc_flags = _load_hgnc_gene_flags(hgnc_path, tf_symbols=tf_symbols)
        click.echo(f"  Loaded HGNC gene flags for {len(hgnc_flags)} genes")

    # Load NIMH priority gene list
    nimh_genes: set[str] = set()
    if nimh_csv_path and nimh_csv_path.exists():
        nimh_genes = _load_nimh_priority_genes(nimh_csv_path)
        click.echo(f"  Loaded NIMH priority gene list: {len(nimh_genes)} unique genes")

    click.echo(f"  Found {len(tables_with_pvalues)} tables with p-value columns")

    # Build symbol/HGNC lookups for gene flags
    symbol_lookup: dict[int, str] = {}
    hgnc_id_lookup: dict[int, str | None] = {}
    rows_gene = conn.execute(
        "SELECT id, human_symbol, hgnc_id FROM central_gene WHERE human_symbol IS NOT NULL"
    ).fetchall()
    for row in rows_gene:
        symbol_lookup[row[0]] = row[1]
        hgnc_id_lookup[row[0]] = row[2]

    def get_gene_flags(gene_id: int) -> str | None:
        flags: set[str] = set()
        symbol = symbol_lookup.get(gene_id)
        if symbol and hgnc_flags:
            flag_str = hgnc_flags.get(symbol)
            if flag_str:
                flags.update(flag_str.split(","))
        hgnc_id = hgnc_id_lookup.get(gene_id)
        if not hgnc_id:
            flags.add("no_hgnc")
        if symbol and symbol in nimh_genes:
            flags.add("nimh_priority")
        return ",".join(sorted(flags)) if flags else None

    # Strip assay/disease columns for the core computation (expects 3-tuples)
    tables_3col = [(t[0], t[1], t[2]) for t in tables_with_pvalues]

    # 2. Build assay and disease groupings for 2D split
    assay_to_tables: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    disease_to_tables: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    combo_to_tables: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)

    for table_name, pvalue_col, link_tables, assay_raw, disease_raw in tables_with_pvalues:
        assay_keys = [a.strip() for a in (assay_raw or "").split(",") if a.strip()]
        disease_keys = [d.strip() for d in (disease_raw or "").split(",") if d.strip()]

        entry = (table_name, pvalue_col, link_tables)

        for ak in assay_keys:
            assay_to_tables[ak].append(entry)
        for dk in disease_keys:
            disease_to_tables[dk].append(entry)
        for ak in assay_keys:
            for dk in disease_keys:
                combo_to_tables[(ak, dk)].append(entry)

    # 3. Build list of all groups to compute
    #   direction == None: legacy "drop perturbed only when both sides exist" rule
    #   direction == "target" / "perturbed": direction-aware filter (drives the
    #   gene-search flip toggle; see issues #65 / #66)
    groups: list[ComputeGroup] = []

    # Global group (min_tables=1: always compute even with a single source table)
    groups.append(ComputeGroup(
        tables=tables_3col,
        out_table="gene_combined_pvalues",
        label="[global] ",
        min_tables=1,
    ))

    # Direction-specific globals (drive the target/perturbed flip toggle).
    groups.append(ComputeGroup(
        tables=tables_3col,
        out_table="gene_combined_pvalues_target",
        label="[target] ",
        min_tables=1,
        direction="target",
    ))
    groups.append(ComputeGroup(
        tables=tables_3col,
        out_table="gene_combined_pvalues_perturbed",
        label="[perturbed] ",
        min_tables=1,
        direction="perturbed",
    ))

    # Per-assay groups (min_tables=2: skip if only 1 source table)
    for assay_key in sorted(assay_to_tables.keys()):
        groups.append(ComputeGroup(
            tables=assay_to_tables[assay_key],
            out_table=f"gene_combined_pvalues_{assay_key}",
            label=f"[assay={assay_key}] ",
            assay_filter=assay_key,
            min_tables=2,
        ))

    # Per-disease groups
    for disease_key in sorted(disease_to_tables.keys()):
        groups.append(ComputeGroup(
            tables=disease_to_tables[disease_key],
            out_table=f"gene_combined_pvalues_d_{disease_key}",
            label=f"[disease={disease_key}] ",
            disease_filter=disease_key,
            min_tables=2,
        ))

    # Per-(assay × disease) groups
    for (assay_key, disease_key) in sorted(combo_to_tables.keys()):
        groups.append(ComputeGroup(
            tables=combo_to_tables[(assay_key, disease_key)],
            out_table=f"gene_combined_pvalues_{assay_key}_d_{disease_key}",
            label=f"[assay={assay_key}, disease={disease_key}] ",
            assay_filter=assay_key,
            disease_filter=disease_key,
            min_tables=2,
        ))

    # Phase 1: Collect p-values from DB for all groups (sequential — fast)
    click.echo(f"\n  Collecting p-values for {len(groups)} group(s)...")
    collected: list[CollectedGroup] = []

    for group in groups:
        # Deduplicate tables
        unique_tables = list({t[0]: t for t in group.tables}.values())
        if len(unique_tables) < group.min_tables:
            click.echo(
                f"  {group.label}Skipping — only {len(unique_tables)} source table(s)"
            )
            collected.append(CollectedGroup(
                pvalues=CollectedPvalues(),
                out_table=group.out_table,
                label=group.label,
                assay_filter=group.assay_filter,
                disease_filter=group.disease_filter,
                use_gene_flags=group.use_gene_flags,
            ))
            continue

        click.echo(f"  {group.label}Collecting from {len(unique_tables)} tables...")
        pvals = _collect_pvalues_for_tables(
            conn, unique_tables, group.label, direction=group.direction,
        )
        collected.append(CollectedGroup(
            pvalues=pvals,
            out_table=group.out_table,
            label=group.label,
            assay_filter=group.assay_filter,
            disease_filter=group.disease_filter,
            use_gene_flags=group.use_gene_flags,
        ))

    # Phase 2: Run R meta-analyses in parallel (slow — this is the bottleneck)
    r_jobs: list[RJobInput] = [
        RJobInput(idx=i, pvalues=cg.pvalues, label=cg.label)
        for i, cg in enumerate(collected)
        if not cg.pvalues.is_empty()
    ]

    max_workers = min(len(r_jobs), os.cpu_count() or 4) if r_jobs else 1
    click.echo(f"\n  Launching {len(r_jobs)} R meta-analysis job(s) with {max_workers} parallel workers...")

    r_results_by_idx: dict[int, dict[int, GeneCombinedPvalues]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx: dict[Any, tuple[int, str]] = {}
        for job in r_jobs:
            click.echo(f"  {job.label}Submitting R job...")
            future = executor.submit(_call_r_combine, job.pvalues)
            future_to_idx[future] = (job.idx, job.label)

        for future in as_completed(future_to_idx):
            idx, label = future_to_idx[future]
            try:
                result = future.result()
                r_results_by_idx[idx] = result if result is not None else {}
                click.echo(f"  {label}R job completed.")
            except Exception as e:
                click.echo(click.style(
                    f"  {label}R job failed: {e}", fg="red",
                ))
                r_results_by_idx[idx] = {}

    # Phase 3: Write results to DB (sequential — fast)
    click.echo("\n  Writing results to database...")

    # Create metadata table
    conn.execute(
        """CREATE TABLE IF NOT EXISTS combined_pvalue_groups (
        assay_filter TEXT,
        disease_filter TEXT,
        table_name TEXT,
        num_source_tables INTEGER,
        PRIMARY KEY (assay_filter, disease_filter)
        )"""
    )

    for i, cg in enumerate(collected):
        if cg.pvalues.is_empty():
            # Group was skipped (< min_tables source tables)
            conn.execute(
                "INSERT INTO combined_pvalue_groups (assay_filter, disease_filter, table_name, num_source_tables) "
                "VALUES (?, ?, NULL, ?)",
                (cg.assay_filter, cg.disease_filter, len(cg.pvalues.per_table)),
            )
            conn.commit()
            continue

        r_results = r_results_by_idx.get(i, {})
        flags_fn = get_gene_flags if cg.use_gene_flags else None

        _write_combined_results(
            conn, cg.out_table, cg.pvalues, r_results, no_index, flags_fn, cg.label,
        )

        # Count source tables for metadata
        num_source = len({
            tbl for gene_tbls in cg.pvalues.per_table.values() for tbl in gene_tbls
        })
        conn.execute(
            "INSERT INTO combined_pvalue_groups (assay_filter, disease_filter, table_name, num_source_tables) "
            "VALUES (?, ?, ?, ?)",
            (cg.assay_filter, cg.disease_filter, cg.out_table, num_source),
        )
        conn.commit()
