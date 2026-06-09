"""R-process integration for the combined-p-values pipeline.

Statistical computation is delegated to R via subprocess, using reference
implementations from the poolr, ACAT, and harmonicmeanp packages. This
module owns:

- locating the Rscript binary and ensuring required packages are installed
  (in a project-local library, since the system library is often read-only)
- writing the per-table-collapsed and raw-p-value CSVs the R script reads
- parsing the R script's results.csv into `GeneCombinedPvalues` records
- the public `call_r_combine` function used as the R-job entry point
"""

import csv
import math
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import click

from . import r_cache
from .data import CollectedPvalues, GeneCombinedPvalues


# Path to the R script that computes combined p-values
_R_SCRIPT = Path(__file__).parent.parent / "r" / "compute_combined.R"

_REQUIRED_R_PACKAGES = ["poolr", "ACAT", "harmonicmeanp"]

# User-local R library, used when the system library is not writable
_R_USER_LIB = Path(__file__).parent.parent / "r" / "lib"

# Env var override for which Rscript to invoke. Set this to a known-good
# Rscript (e.g. one matching libgfortran versions on the host) when `which
# Rscript` would pick up a system R that doesn't satisfy our packages.
_RSCRIPT_ENV_VAR = "SSPSYGENE_RSCRIPT"

# One-time-per-run memo for R readiness. Without this, every parallel R job
# independently re-runs the resolve + (failing) package install, spamming dozens
# of concurrent install attempts that race on the shared project lib and never
# converge. `prepare_r()` runs the check at most once per run (guarded by the
# lock); `reset_r_prep()` clears it at the start of each run so a later run
# re-evaluates (e.g. after packages were installed manually).
_R_PREP_LOCK = threading.Lock()
_r_prep_done = False
_r_ready = False
_r_rscript: str | None = None

_MANUAL_INSTALL_HINT = (
    "  To enable combined p-values, install R and the required packages once:\n"
    "    Rscript -e 'install.packages(c(\"poolr\",\"harmonicmeanp\",\"remotes\"), "
    'repos="https://cloud.r-project.org")\'\n'
    "    Rscript -e 'remotes::install_github(\"yaowuliu/ACAT\")'\n"
    f'  (or into the project library: lib="{_R_USER_LIB}").\n'
    "  If a package fails to compile, install a build toolchain first\n"
    "    macOS:        xcode-select --install   (and `brew install gcc` for gfortran)\n"
    "    Debian/Ubuntu: apt install r-base-dev\n"
    f"  Then re-run, or point {_RSCRIPT_ENV_VAR} at a known-good Rscript.\n"
)


def reset_r_prep() -> None:
    """Clear the memoized R-readiness state. Call once at the start of a run."""
    global _r_prep_done, _r_ready, _r_rscript
    with _R_PREP_LOCK:
        _r_prep_done = False
        _r_ready = False
        _r_rscript = None


def prepare_r() -> str | None:
    """Resolve Rscript and ensure required packages — at most once per run.

    Memoized under a lock so that concurrent R jobs trigger a single resolve +
    install attempt rather than one per job. Returns the Rscript path when R is
    ready, or None (printing a one-time warning + manual-install instructions)
    when it is not. Call `reset_r_prep()` at the start of a run to re-evaluate.
    """
    global _r_prep_done, _r_ready, _r_rscript
    with _R_PREP_LOCK:
        if _r_prep_done:
            return _r_rscript if _r_ready else None
        _r_prep_done = True

        rscript = _resolve_rscript()
        if rscript is None:
            click.echo(
                click.style(
                    "\n  WARNING: Rscript not found on PATH. Combined p-values "
                    "will not be computed (the database still loads).\n"
                    + _MANUAL_INSTALL_HINT,
                    fg="yellow",
                    bold=True,
                )
            )
            return None

        if not _ensure_r_packages(rscript):
            click.echo(
                click.style(
                    "\n  WARNING: Required R packages are unavailable. Combined "
                    "p-values will not be computed (the database still loads).\n"
                    + _MANUAL_INSTALL_HINT,
                    fg="yellow",
                    bold=True,
                )
            )
            return None

        _r_rscript = rscript
        _r_ready = True
        return rscript


def _resolve_rscript() -> str | None:
    """Return the Rscript path to invoke, honoring SSPSYGENE_RSCRIPT first."""
    override = os.environ.get(_RSCRIPT_ENV_VAR)
    if override:
        if not Path(override).is_file():
            click.echo(
                click.style(
                    f"\n  WARNING: {_RSCRIPT_ENV_VAR}={override} is not a file. "
                    "Falling back to PATH.\n",
                    fg="yellow",
                    bold=True,
                )
            )
        else:
            return override
    return shutil.which("Rscript")


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
        setup + "; " + "; ".join(f"library({pkg})" for pkg in _REQUIRED_R_PACKAGES)
    )
    check = subprocess.run(
        [rscript, "-e", check_code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
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
            [
                rscript,
                "-e",
                f'{setup}; install.packages(c({pkg_list}), lib="{lib_path}", '
                f'repos="https://cloud.r-project.org", quiet=TRUE)',
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if install.returncode != 0:
            click.echo(
                click.style(
                    f"  Failed to install CRAN packages:\n{install.stderr.strip()}",
                    fg="yellow",
                    bold=True,
                )
            )

    # ACAT is not on CRAN; install from GitHub via remotes
    acat_check = subprocess.run(
        [rscript, "-e", f"{setup}; library(ACAT)"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if acat_check.returncode != 0:
        click.echo("  Attempting to install ACAT from GitHub...")
        acat_install = subprocess.run(
            [
                rscript,
                "-e",
                f"{setup}; "
                f'if (!requireNamespace("remotes", quietly=TRUE)) '
                f'install.packages("remotes", lib="{lib_path}", '
                f'repos="https://cloud.r-project.org", quiet=TRUE); '
                f'remotes::install_github("yaowuliu/ACAT", lib="{lib_path}", quiet=TRUE)',
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if acat_install.returncode != 0:
            click.echo(
                click.style(
                    f"  Failed to install ACAT:\n{acat_install.stderr.strip()}",
                    fg="yellow",
                    bold=True,
                )
            )

    # Verify all packages
    verify = subprocess.run(
        [rscript, "-e", check_code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if verify.returncode != 0:
        click.echo(
            click.style(
                "\n  WARNING: Required R packages could not be installed. "
                "Combined p-values will not be computed.\n",
                fg="yellow",
                bold=True,
            )
        )
        return False
    return True


def write_r_inputs(tmp_dir: Path, pvalues: CollectedPvalues) -> None:
    """Write the per-table-collapsed and raw p-value CSVs the R script reads.

    Delegates byte generation to `r_cache` so the on-disk bytes match
    exactly what the cache key was hashed over.
    """
    (tmp_dir / "collapsed_pvalues.csv").write_bytes(
        r_cache.collapsed_csv_bytes(pvalues)
    )
    (tmp_dir / "raw_pvalues.csv").write_bytes(
        r_cache.raw_csv_bytes(pvalues)
    )


def parse_r_results(results_path: Path) -> dict[int, GeneCombinedPvalues]:
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
                cauchy_p=_parse_cell(row["cauchy_p"]),
                cauchy_fdr=_parse_cell(row["cauchy_fdr"]),
                hmp_p=_parse_cell(row["hmp_p"]),
                hmp_fdr=_parse_cell(row["hmp_fdr"]),
            )
    return gene_results


def call_r_combine(
    pvalues: CollectedPvalues,
    use_cache: bool = True,
) -> dict[int, GeneCombinedPvalues] | None:
    """Call R to compute combined p-values and FDR corrections.

    Writes input CSVs, invokes Rscript, reads result CSV. Returns the
    per-gene combined p-values, or None if R is unavailable. When
    `use_cache` is True (default), checks the content-addressed cache
    in `r_cache` before invoking R, and stores results on miss.
    """
    if not _R_SCRIPT.exists():
        click.echo(
            click.style(
                f"\n  WARNING: R script not found: {_R_SCRIPT}. "
                "Combined p-values will not be computed.\n",
                fg="yellow",
                bold=True,
            )
        )
        return None

    # Cache check first — avoid mkdtemp + disk writes on a hit.
    cache_key: str | None = None
    if use_cache:
        cache_key = r_cache.compute_key_from_pvalues(pvalues, _R_SCRIPT)
        hit = r_cache.lookup(cache_key)
        if hit is not None:
            click.echo(f"  R cache hit ({cache_key[:12]})")
            return parse_r_results(hit)

    tmp_dir = Path(tempfile.mkdtemp(prefix="sspsygene_combine_"))
    try:
        write_r_inputs(tmp_dir, pvalues)

        # Resolve Rscript + ensure packages once per run (memoized under a
        # lock), so concurrent jobs don't each re-attempt the install.
        rscript = prepare_r()
        if rscript is None:
            return None

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

        if use_cache and cache_key is not None:
            r_cache.store(cache_key, results_path)

        return parse_r_results(results_path)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
