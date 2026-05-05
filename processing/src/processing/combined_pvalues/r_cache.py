"""Content-addressed cache for R meta-analysis results.

The R script (`compute_combined.R`) is deterministic given its CSV inputs,
so when the same inputs recur across `load-db` runs we can skip Rscript
entirely. Cache key = SHA-256 over `{collapsed_pvalues.csv bytes,
raw_pvalues.csv bytes, compute_combined.R bytes}` — including the script
auto-invalidates when the R logic changes. Cached entries are stored as
flat files: `<cache_dir>/<sha>.csv`.

Test/production isolation is enforced by the hash itself: `--test` runs
filter genes upstream, producing strictly different input bytes from
production runs, so their hashes never collide.
"""

import csv
import hashlib
import io
import os
import shutil
from pathlib import Path

from .collection import precollapse
from .data import CollectedPvalues


_DEFAULT_CACHE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "r-cache"
)


def cache_dir() -> Path:
    """Resolve the cache directory, honoring SSPSYGENE_R_CACHE_DIR.

    Defaults to `processing/r-cache/` (sibling of `src/`). Created on first
    call; safe to invoke repeatedly.
    """
    override = os.environ.get("SSPSYGENE_R_CACHE_DIR")
    out = Path(override) if override else _DEFAULT_CACHE_DIR
    out.mkdir(parents=True, exist_ok=True)
    return out


def collapsed_csv_bytes(pvalues: CollectedPvalues) -> bytes:
    """Build the bytes of the collapsed_pvalues.csv R input in memory.

    Byte-for-byte identical to what `write_r_inputs` writes to disk: same
    csv.writer dialect (CRLF line terminator), same row order (genes
    sorted, per-table buckets in dict-iteration order), same scientific
    formatting `:.17e`. So a hash computed over these bytes matches one
    computed over the on-disk file.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["gene_id", "pvalue"])
    for gene_id in sorted(pvalues.per_table.keys()):
        for tbl_pvals in pvalues.per_table[gene_id].values():
            collapsed = precollapse(tbl_pvals)
            writer.writerow([gene_id, f"{collapsed:.17e}"])
    return buf.getvalue().encode("utf-8")


def raw_csv_bytes(pvalues: CollectedPvalues) -> bytes:
    """Build the bytes of the raw_pvalues.csv R input in memory.

    See `collapsed_csv_bytes` for the byte-equivalence guarantee.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["gene_id", "pvalue"])
    for gene_id in sorted(pvalues.all_pvalues.keys()):
        for pval in pvalues.all_pvalues[gene_id]:
            writer.writerow([gene_id, f"{pval:.17e}"])
    return buf.getvalue().encode("utf-8")


def _frame(h: "hashlib._Hash", name: str, data: bytes) -> None:
    """Length-prefixed framing so concat (a, b) cannot collide with (a', b')."""
    h.update(name.encode("utf-8"))
    h.update(b"\0")
    h.update(len(data).to_bytes(8, "big"))
    h.update(data)


def compute_key(tmp_dir: Path, r_script: Path) -> str:
    """SHA-256 key derived from R input CSVs already on disk.

    `tmp_dir` is the directory `write_r_inputs` populated; we hash the two
    input CSVs in a fixed order with length-prefix separators so that no
    pair of (csv_a_bytes, csv_b_bytes) can collide with a different pair
    by concatenation.
    """
    h = hashlib.sha256()
    for name in ("collapsed_pvalues.csv", "raw_pvalues.csv"):
        _frame(h, name, (tmp_dir / name).read_bytes())
    _frame(h, "compute_combined.R", r_script.read_bytes())
    return h.hexdigest()


def compute_key_from_pvalues(
    pvalues: CollectedPvalues, r_script: Path
) -> str:
    """Same hash as `compute_key`, but built without writing CSVs to disk.

    Used on the cache-check path so a cache hit avoids `mkdtemp` + the disk
    round-trip. The byte sequence fed into SHA-256 is byte-identical to
    what `compute_key` would produce over freshly-written input CSVs.
    """
    h = hashlib.sha256()
    _frame(h, "collapsed_pvalues.csv", collapsed_csv_bytes(pvalues))
    _frame(h, "raw_pvalues.csv", raw_csv_bytes(pvalues))
    _frame(h, "compute_combined.R", r_script.read_bytes())
    return h.hexdigest()


def lookup(key: str) -> Path | None:
    """Return the cached results.csv path if present, else None."""
    candidate = cache_dir() / f"{key}.csv"
    return candidate if candidate.exists() else None


def store(key: str, results_csv: Path) -> None:
    """Atomically copy `results_csv` into the cache as `<key>.csv`."""
    dest = cache_dir() / f"{key}.csv"
    tmp = dest.with_suffix(".csv.tmp")
    shutil.copyfile(results_csv, tmp)
    os.replace(tmp, dest)
