"""R-process integration for the combined-p-values pipeline.

Statistical computation is delegated to R via subprocess, using reference
implementations from the poolr, ACAT, and harmonicmeanp packages. This
module owns:

- locating the Rscript binary and ensuring required packages are installed
  (in a project-local library, since the system library is often read-only)
- writing the per-table-collapsed and raw-p-value CSVs the R script reads
- parsing the R script's results.csv into `GeneCombinedPvalues` records
- the public `_call_r_combine` function used as the R-job entry point
"""

import csv
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import click

from .collection import _precollapse
from .data import CollectedPvalues, GeneCombinedPvalues


# Path to the R script that computes combined p-values
_R_SCRIPT = Path(__file__).parent.parent / "r" / "compute_combined.R"

_REQUIRED_R_PACKAGES = ["poolr", "ACAT", "harmonicmeanp"]

# User-local R library, used when the system library is not writable
_R_USER_LIB = Path(__file__).parent.parent / "r" / "lib"


def _r_lib_setup_code() -> str:
    """R code to prepend our user library to .libPaths()."""
    lib_path = str(_R_USER_LIB).replace("\\", "/")
    return (
        f'dir.create("{lib_path}", recursive=TRUE, showWarnings=FALSE); '
        f'.libPaths(c("{lib_path}", .libPaths()))'
    )


def _ensure_r_packages(rscript: str) -> bool:
    """Check for required R packages; attempt to install if missing.

    Returns True if all packages are available, False otherwise.
    Uses a project-local R library to avoid requiring write access
    to the system R library.
    """
    setup = _r_lib_setup_code()
    check_code = (
        setup + "; "
        + "; ".join(f"library({pkg})" for pkg in _REQUIRED_R_PACKAGES)
    )
    check = subprocess.run(
        [rscript, "-e", check_code],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if check.returncode == 0:
        return True

    lib_path = str(_R_USER_LIB).replace("\\", "/")

    # Try to install missing CRAN packages
    cran_pkgs = [p for p in _REQUIRED_R_PACKAGES if p != "ACAT"]
    if cran_pkgs:
        pkg_list = ", ".join(f'"{p}"' for p in cran_pkgs)
        click.echo(
            f"  Attempting to install missing R packages "
            f"({', '.join(cran_pkgs)})..."
        )
        install = subprocess.run(
            [rscript, "-e",
             f'{setup}; install.packages(c({pkg_list}), lib="{lib_path}", '
             f'repos="https://cloud.r-project.org", quiet=TRUE)'],
            capture_output=True, text=True, timeout=300, check=False,
        )
        if install.returncode != 0:
            click.echo(click.style(
                f"  Failed to install CRAN packages:\n{install.stderr.strip()}",
                fg="yellow", bold=True,
            ))

    # ACAT is not on CRAN; install from GitHub via remotes
    acat_check = subprocess.run(
        [rscript, "-e", f'{setup}; library(ACAT)'],
        capture_output=True, text=True, timeout=30, check=False,
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
            capture_output=True, text=True, timeout=300, check=False,
        )
        if acat_install.returncode != 0:
            click.echo(click.style(
                f"  Failed to install ACAT:\n{acat_install.stderr.strip()}",
                fg="yellow", bold=True,
            ))

    # Verify all packages
    verify = subprocess.run(
        [rscript, "-e", check_code],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if verify.returncode != 0:
        click.echo(click.style(
            "\n  WARNING: Required R packages could not be installed. "
            "Combined p-values will not be computed.\n",
            fg="yellow", bold=True,
        ))
        return False
    return True


def _write_r_inputs(tmp_dir: Path, pvalues: CollectedPvalues) -> None:
    """Write the per-table-collapsed and raw p-value CSVs the R script reads."""
    collapsed_path = tmp_dir / "collapsed_pvalues.csv"
    with open(collapsed_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["gene_id", "pvalue"])
        for gene_id in sorted(pvalues.per_table.keys()):
            for tbl_pvals in pvalues.per_table[gene_id].values():
                collapsed = _precollapse(tbl_pvals)
                writer.writerow([gene_id, f"{collapsed:.17e}"])

    raw_path = tmp_dir / "raw_pvalues.csv"
    with open(raw_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["gene_id", "pvalue"])
        for gene_id in sorted(pvalues.all_pvalues.keys()):
            for pval in pvalues.all_pvalues[gene_id]:
                writer.writerow([gene_id, f"{pval:.17e}"])


def _parse_r_results(results_path: Path) -> dict[int, GeneCombinedPvalues]:
    """Parse R's results.csv into per-gene combined-p-value records."""
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


def _call_r_combine(
    pvalues: CollectedPvalues,
) -> dict[int, GeneCombinedPvalues] | None:
    """Call R to compute combined p-values and FDR corrections.

    Writes input CSVs, invokes Rscript, reads result CSV. Returns the
    per-gene combined p-values, or None if R is unavailable.
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

    tmp_dir = Path(tempfile.mkdtemp(prefix="sspsygene_combine_"))
    try:
        _write_r_inputs(tmp_dir, pvalues)

        result = subprocess.run(
            [rscript, str(_R_SCRIPT), str(tmp_dir)],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )

        if result.stdout:
            for line in result.stdout.strip().splitlines():
                click.echo(line)

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(
                f"R script failed (exit code {result.returncode}):\n{stderr}"
            )

        results_path = tmp_dir / "results.csv"
        if not results_path.exists():
            raise RuntimeError(f"R script did not produce {results_path}")

        return _parse_r_results(results_path)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
