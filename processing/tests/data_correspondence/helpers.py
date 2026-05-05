"""Shared helpers for the data-correspondence tests (#113).

Two responsibilities:

1. Enumerate every primary table in the repo by walking
   `data/datasets/*/config.yaml` (via the existing `TablesConfig` loader)
   so each test family parametrizes over the same canonical list.

2. Load and validate the per-dataset `expected_drops.yaml` manifests, and
   write `.proposed` files for the first-run workflow.

The tests under this directory rely on three on-disk artifacts:

* `data/datasets/<name>/config.yaml` (always present, in git)
* `data/datasets/<name>/<cleaned>.preprocessing.yaml` sidecars (in git when
  the dataset has a Pipeline-based preprocess.py — the row-accounting
  family runs against just these and the manifest)
* `data/db/sspsygene.db` and the raw/cleaned CSVs themselves (gitignored;
  spot-check tests skip when absent)
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml


# ---------------------------------------------------------------------------
# Repo path discovery
# ---------------------------------------------------------------------------

# This file lives at <repo>/processing/tests/data_correspondence/helpers.py
_HELPERS = Path(__file__).resolve()
REPO_ROOT = _HELPERS.parents[3]

# `data/` in the current checkout — holds git-tracked artifacts (config.yaml,
# preprocessing.yaml sidecars, expected_drops.yaml manifests). Always read
# manifest/sidecar metadata from here so a wrangler editing files in their
# worktree sees those edits applied.
GIT_DATA_DIR = REPO_ROOT / "data"
DATASETS_DIR = GIT_DATA_DIR / "datasets"


def payload_data_dir() -> Path:
    """Where the gitignored payload (raw CSVs, the SQLite DB) actually lives.

    Defaults to `<repo>/data/`. Override with `SSPSYGENE_DATA_DIR` to point
    at the main checkout from a worktree (per CLAUDE.md: don't symlink the
    data/ directory itself).
    """
    override = os.environ.get("SSPSYGENE_DATA_DIR")
    return Path(override) if override else GIT_DATA_DIR


def payload_dataset_dir(dataset: str) -> Path:
    """Dataset directory under the payload data dir (for raw/cleaned CSVs)."""
    return payload_data_dir() / "datasets" / dataset


def db_path() -> Path:
    """Resolve the live DB path, honoring SSPSYGENE_DATA_DB."""
    override = os.environ.get("SSPSYGENE_DATA_DB")
    if override:
        return Path(override)
    return payload_data_dir() / "db" / "sspsygene.db"


def open_db_readonly() -> sqlite3.Connection:
    """Open the live SQLite read-only. Raises if the file is missing."""
    p = db_path()
    if not p.exists():
        raise FileNotFoundError(f"DB not found at {p}")
    # `mode=ro` won't create the file even if missing, and prevents writes.
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Primary-table enumeration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrimaryTable:
    """A single (dataset, table) pair drawn from the per-dataset YAMLs.

    Carries just the bits the data-correspondence tests need; lifting the
    full TableToProcessConfig would couple us to fields the tests don't use
    and force a heavier import (central_gene_table is imported lazily by
    that class but loads HGNC at first use).

    `dataset_dir` points at the git-tracked dataset dir (config.yaml,
    sidecars, manifest). `in_path_name` is the filename the wrangler set in
    config.yaml; resolve it via `payload_in_path()` for actual file reads
    (the file is gitignored and may live in a different checkout when
    running from a worktree).
    """

    dataset: str
    dataset_dir: Path  # git-tracked dir for sidecars / manifests
    table_name: str  # SQL identifier; matches data_tables.table_name
    short_label: str
    in_path_name: str  # bare filename from config.yaml's in_path
    separator: str
    gene_columns: tuple[str, ...]  # raw, pre-normalize column names from YAML
    gene_species: tuple[str, ...]
    pvalue_column: str | None  # already normalized to SQL column name
    fdr_column: str | None
    effect_column: str | None

    @property
    def sidecar_path(self) -> Path:
        """Sidecar lives next to the cleaned file in the git-tracked tree."""
        return self.dataset_dir / (self.in_path_name + ".preprocessing.yaml")

    @property
    def payload_in_path(self) -> Path:
        """Path to the cleaned file on disk (under SSPSYGENE_DATA_DIR if set)."""
        return payload_dataset_dir(self.dataset) / self.in_path_name


def _normalize_col(name: str) -> str:
    """Mirror processing.types.table_to_process_config.normalize_column_name."""
    out = name.lower()
    out = re.sub(r"[^a-z0-9_]", "_", out)
    out = re.sub(r"_+", "_", out)
    return out


def enumerate_primary_tables() -> list[PrimaryTable]:
    """Walk data/datasets/*/config.yaml and return one entry per table.

    Sorted by (dataset, table_name) for stable parametrize IDs.
    """
    tables: list[PrimaryTable] = []
    for cfg_path in sorted(DATASETS_DIR.glob("*/config.yaml")):
        loaded = yaml.safe_load(cfg_path.read_text())
        if not loaded:
            continue
        dataset = cfg_path.parent.name
        for entry in loaded.get("tables", []) or []:
            sep = entry.get("separator", "\t")
            mappings = entry.get("gene_mappings", []) or []
            gene_cols = tuple(m["column_name"] for m in mappings)
            species = tuple(m["species"] for m in mappings)

            def _norm_or_none(raw: Any) -> str | None:
                if raw is None:
                    return None
                if isinstance(raw, list):
                    return ",".join(_normalize_col(c) for c in raw) or None
                return _normalize_col(raw)

            tables.append(
                PrimaryTable(
                    dataset=dataset,
                    dataset_dir=cfg_path.parent,
                    table_name=entry["table"],
                    short_label=entry.get("shortLabel", entry["table"]),
                    in_path_name=entry["in_path"],
                    separator=sep,
                    gene_columns=gene_cols,
                    gene_species=species,
                    pvalue_column=_norm_or_none(entry.get("pvalue_column")),
                    fdr_column=_norm_or_none(entry.get("fdr_column")),
                    effect_column=_norm_or_none(entry.get("effect_column")),
                )
            )
    return sorted(tables, key=lambda t: (t.dataset, t.table_name))


# ---------------------------------------------------------------------------
# Sidecar loading
# ---------------------------------------------------------------------------

def load_sidecar(table: PrimaryTable) -> dict[str, Any] | None:
    """Load the sidecar for a table, or None if no sidecar is on disk."""
    p = table.sidecar_path
    if not p.exists():
        return None
    loaded = yaml.safe_load(p.read_text())
    if not isinstance(loaded, dict):
        return None
    return loaded


def sidecar_drop_total(sidecar: dict[str, Any]) -> int:
    """Sum of every drop-emitting step in the sidecar.

    `clean_gene_column.dropped_rows`, `dropna.dropped`, `filter_rows.dropped`.
    Other step types don't drop rows.
    """
    total = 0
    for action in sidecar.get("actions", []) or []:
        step = action.get("step")
        if step == "clean_gene_column":
            total += int(action.get("dropped_rows", 0) or 0)
        elif step in ("dropna", "filter_rows"):
            total += int(action.get("dropped", 0) or 0)
    return total


def sidecar_first_read_rows(sidecar: dict[str, Any]) -> int | None:
    """Rows recorded by the first read step (read_csv or from_dataframe).

    Returns None for `copy_file` (the action doesn't record a row count)
    and for `concat_and_write` (the multi-sheet pipelines record only the
    aggregate output rows, not the per-sheet inputs).
    """
    for action in sidecar.get("actions", []) or []:
        if action.get("step") in ("read_csv", "from_dataframe"):
            rows = action.get("rows")
            if isinstance(rows, int):
                return rows
    return None


def sidecar_final_write_rows(sidecar: dict[str, Any]) -> int | None:
    """Rows recorded by the last write step (write_csv or concat_and_write).

    `copy_file` doesn't record a row count — return None and let the test
    fall back to a file-rowcount or DB check.
    """
    last = None
    for action in sidecar.get("actions", []) or []:
        if action.get("step") in ("write_csv", "concat_and_write"):
            rows = action.get("rows")
            if isinstance(rows, int):
                last = rows
    return last


def sidecar_is_copy_file(sidecar: dict[str, Any]) -> bool:
    """True when the sidecar's only action is a verbatim file copy."""
    actions = sidecar.get("actions", []) or []
    return len(actions) == 1 and actions[0].get("step") == "copy_file"


# ---------------------------------------------------------------------------
# Per-dataset manifest loading + proposed-manifest workflow
# ---------------------------------------------------------------------------

def manifest_path_for(dataset_dir: Path) -> Path:
    return dataset_dir / "expected_drops.yaml"


def proposed_manifest_path_for(dataset_dir: Path) -> Path:
    return dataset_dir / "expected_drops.yaml.proposed"


def load_manifest(dataset_dir: Path) -> dict[str, Any] | None:
    """Load the per-dataset manifest, or None if absent."""
    p = manifest_path_for(dataset_dir)
    if not p.exists():
        return None
    loaded = yaml.safe_load(p.read_text())
    if not isinstance(loaded, dict):
        return None
    return loaded


def manifest_entry_for(table: PrimaryTable) -> dict[str, Any] | None:
    """Look up `tables[table_name]` in the dataset's manifest."""
    manifest = load_manifest(table.dataset_dir)
    if not manifest:
        return None
    return (manifest.get("tables") or {}).get(table.table_name)


def _count_csv_rows(path: Path, sep: str) -> int | None:
    """Count data rows in a CSV/TSV using pandas (matches load-db's parser).

    A naive line count is wrong for files with quoted multi-line cells —
    `SFARI-Gene_animal-rescues_*.csv` has two such cells and was off by 2.
    We mirror `load_data_table`'s `pd.read_csv(sep=...)` so the rowcount
    here matches what eventually lands in the DB.
    """
    if not path.exists():
        return None
    import pandas as pd

    return len(pd.read_csv(path, sep=sep, dtype=str))


def derive_manifest_entry(table: PrimaryTable) -> dict[str, Any]:
    """Build a manifest entry for a table from live state.

    Pulls counts from the sidecar (when present) and `db_rows` from the
    SQLite file (when present). Used both for the proposed-manifest
    workflow and for an auditable record of what the live state looked
    like at manifest creation time.
    """
    entry: dict[str, Any] = {
        "raw_file": table.in_path_name,
    }
    sidecar = load_sidecar(table)
    if sidecar is not None:
        entry["pipeline_used"] = True

        # `inputs:` lists the underlying raw file(s); use the first one so
        # `raw_file` reflects the actual source rather than the cleaned in_path.
        inputs = sidecar.get("inputs") or []
        if inputs and isinstance(inputs, list):
            entry["raw_file"] = inputs[0]
        if table.in_path_name != entry["raw_file"]:
            entry["cleaned_file"] = table.in_path_name

        first_rows = sidecar_first_read_rows(sidecar)
        final_rows = sidecar_final_write_rows(sidecar)

        if sidecar_is_copy_file(sidecar):
            # copy_file is a verbatim copy — raw == cleaned. We can't read
            # the count from the action itself, so count the file on disk
            # when present.
            file_rows = _count_csv_rows(table.payload_in_path, table.separator)
            if file_rows is not None:
                entry["raw_rows"] = file_rows
                entry["cleaned_rows"] = file_rows
        else:
            if first_rows is not None:
                entry["raw_rows"] = first_rows
            if final_rows is not None:
                entry["cleaned_rows"] = final_rows

        # Mirror every drop-emitting step's expected counts.
        expected: list[dict[str, Any]] = []
        for action in sidecar.get("actions", []) or []:
            step = action.get("step")
            if step == "clean_gene_column":
                expected.append({
                    "step": "clean_gene_column",
                    "column": action.get("column"),
                    "dropped_rows": int(action.get("dropped_rows", 0) or 0),
                    "counts": dict(action.get("counts") or {}),
                })
            elif step == "dropna":
                expected.append({
                    "step": "dropna",
                    "columns": list(action.get("columns") or []),
                    "dropped": int(action.get("dropped", 0) or 0),
                })
            elif step == "filter_rows":
                expected.append({
                    "step": "filter_rows",
                    "description": action.get("description"),
                    "dropped": int(action.get("dropped", 0) or 0),
                })
        entry["expected_drops"] = expected
    else:
        # No sidecar — either there's no preprocess.py at all (sfari × 3),
        # or it's a custom non-Pipeline script (perturb-fish/extract_pheno.py,
        # zebraAsd/RestWake_VisStart). The contract reduces to raw_rows ==
        # db_rows.
        entry["pipeline_used"] = False
        entry["expected_drops"] = []
        file_rows = _count_csv_rows(table.payload_in_path, table.separator)
        if file_rows is not None:
            entry["raw_rows"] = file_rows

    # DB row count, when the live DB is reachable.
    try:
        with open_db_readonly() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table.table_name}"
            ).fetchone()
            entry["db_rows"] = int(row["n"])
    except (FileNotFoundError, sqlite3.OperationalError):
        pass

    return entry


def write_proposed_manifest(
    dataset_dir: Path, entries: dict[str, dict[str, Any]]
) -> Path:
    """Write/update `expected_drops.yaml.proposed` for a dataset.

    Merges with any existing proposed file so several missing tables in the
    same dataset accumulate into one suggestion the wrangler can review in
    a single pass.
    """
    p = proposed_manifest_path_for(dataset_dir)
    existing: dict[str, Any] = {"tables": {}}
    if p.exists():
        loaded = yaml.safe_load(p.read_text())
        if isinstance(loaded, dict) and isinstance(loaded.get("tables"), dict):
            existing = loaded
    existing.setdefault("tables", {})
    for tname, entry in entries.items():
        existing["tables"][tname] = entry
    p.write_text(
        yaml.safe_dump(existing, sort_keys=False, allow_unicode=True, width=100)
    )
    return p


def iter_primary_tables_grouped() -> Iterator[tuple[Path, list[PrimaryTable]]]:
    """Yield (dataset_dir, [tables]) groups for utilities that batch by dataset."""
    grouped: dict[Path, list[PrimaryTable]] = {}
    for t in enumerate_primary_tables():
        grouped.setdefault(t.dataset_dir, []).append(t)
    for dd in sorted(grouped):
        yield dd, grouped[dd]
