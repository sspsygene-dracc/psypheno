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

import hashlib
import os
import shutil
from pathlib import Path


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


def compute_key(tmp_dir: Path, r_script: Path) -> str:
    """SHA-256 over the bytes R would read, plus the R script itself.

    `tmp_dir` is the directory `write_r_inputs` populated; we hash the two
    input CSVs in a fixed order with length-prefix separators so that no
    pair of (csv_a_bytes, csv_b_bytes) can collide with a different pair
    by concatenation.
    """
    h = hashlib.sha256()
    for name in ("collapsed_pvalues.csv", "raw_pvalues.csv"):
        data = (tmp_dir / name).read_bytes()
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    script_bytes = r_script.read_bytes()
    h.update(b"compute_combined.R\0")
    h.update(len(script_bytes).to_bytes(8, "big"))
    h.update(script_bytes)
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
