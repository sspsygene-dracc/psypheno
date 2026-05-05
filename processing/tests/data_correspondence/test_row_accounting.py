"""Sidecar / manifest invariants — CI-runnable, no DB or raw data needed (#113).

For each primary table, asserts:

  1. The dataset has an `expected_drops.yaml` manifest with an entry for
     this table. Missing entries are auto-derived and written to
     `expected_drops.yaml.proposed` for wrangler review (the test still
     fails so CI catches it).
  2. The sidecar's recorded counts are internally consistent — every
     `clean_gene_column` / `dropna` / `filter_rows` action's drop count
     fits the running tally between `read_csv` and the final `write_csv`.
  3. The manifest's `expected_drops` mirrors the live sidecar exactly. If
     the sidecar drifts (a wrangler ran preprocess.py and counts changed),
     this test fails and the wrangler updates the manifest.

Tables without a sidecar (no preprocess.py or a custom non-Pipeline script)
skip steps 2 and 3; their contract is `raw_rows == db_rows`, verified in
`test_sidecar_vs_files.py`.
"""

from __future__ import annotations

import pytest

from .helpers import (
    PrimaryTable,
    derive_manifest_entry,
    load_manifest,
    load_sidecar,
    manifest_entry_for,
    sidecar_drop_total,
    sidecar_first_read_rows,
    sidecar_final_write_rows,
    write_proposed_manifest,
)


# ---------------------------------------------------------------------------
# 1. Manifest presence + proposed-manifest workflow
# ---------------------------------------------------------------------------

def test_manifest_entry_exists(table: PrimaryTable) -> None:
    """Every primary table must have an entry in its dataset's manifest.

    The first time we see a new table, we write a proposed manifest entry
    so the wrangler can review and merge it. The test still fails — manifests
    are part of the contract.
    """
    entry = manifest_entry_for(table)
    if entry is not None:
        return  # happy path

    # Bootstrap: derive a proposed entry from live state and write it.
    proposed_entry = derive_manifest_entry(table)
    proposed_path = write_proposed_manifest(
        table.dataset_dir, {table.table_name: proposed_entry}
    )
    pytest.fail(
        f"No manifest entry for table {table.table_name!r} in "
        f"{table.dataset_dir.name}/expected_drops.yaml. "
        f"A proposed entry was derived from the live sidecar/DB and written "
        f"to {proposed_path.relative_to(table.dataset_dir.parent.parent.parent)}. "
        f"Review and merge it into expected_drops.yaml, then re-run."
    )


def test_manifest_top_level_only_has_tables_key(table: PrimaryTable) -> None:
    """Don't allow stray top-level keys in the manifest — keep it tight."""
    manifest = load_manifest(table.dataset_dir)
    if manifest is None:
        pytest.skip("manifest missing — covered by test_manifest_entry_exists")
    extra = set(manifest.keys()) - {"tables"}
    assert not extra, f"unexpected top-level keys in manifest: {sorted(extra)}"


# ---------------------------------------------------------------------------
# 2. Sidecar internal consistency
# ---------------------------------------------------------------------------

def test_sidecar_internal_consistency(table: PrimaryTable) -> None:
    """`read_csv.rows - sum(drops) == write_csv.rows` for Pipeline-built tables."""
    sidecar = load_sidecar(table)
    if sidecar is None:
        pytest.skip("no sidecar (no Pipeline preprocess.py for this table)")

    first = sidecar_first_read_rows(sidecar)
    final = sidecar_final_write_rows(sidecar)

    if first is None and final is None:
        # `concat_and_write`-only sidecars (multi-sheet xlsx pipelines)
        # don't record per-sheet inputs in the output's sidecar; nothing
        # internal to verify here.
        pytest.skip("sidecar has no read/write row count (concat_and_write only)")

    if first is None:
        pytest.skip("sidecar has no read step (concat_and_write or copy_file)")

    drops = sidecar_drop_total(sidecar)
    expected_final = first - drops

    if final is None:
        # `copy_file` doesn't record a final row count. Internal walk is
        # vacuously consistent in that case.
        assert drops == 0, (
            f"copy_file sidecar should have zero drops; got {drops}"
        )
        return

    assert final == expected_final, (
        f"sidecar internal inconsistency: read_csv={first}, "
        f"sum(drops)={drops}, write_csv={final}; "
        f"expected write_csv={expected_final}"
    )


# ---------------------------------------------------------------------------
# 3. Manifest expectations vs sidecar reality
# ---------------------------------------------------------------------------

def test_manifest_matches_sidecar(table: PrimaryTable) -> None:
    """Manifest's `expected_drops` mirrors the sidecar exactly.

    Any drift means a wrangler edited preprocess.py without updating the
    manifest — the failure tells them what to bump.
    """
    manifest_entry = manifest_entry_for(table)
    if manifest_entry is None:
        pytest.skip("manifest missing — covered by test_manifest_entry_exists")

    sidecar = load_sidecar(table)

    if sidecar is None:
        # No preprocess.py / custom script. Manifest must agree.
        assert manifest_entry.get("pipeline_used") is False, (
            f"manifest says pipeline_used=True but no sidecar exists for "
            f"{table.table_name!r}"
        )
        assert manifest_entry.get("expected_drops") == [], (
            "expected_drops must be [] when no Pipeline ran"
        )
        return

    assert manifest_entry.get("pipeline_used") is True, (
        f"sidecar exists for {table.table_name!r} but manifest says "
        f"pipeline_used=False"
    )

    # Build the canonical expected_drops list from the live sidecar and
    # compare element-by-element.
    expected = derive_manifest_entry(table)["expected_drops"]
    actual = manifest_entry.get("expected_drops") or []
    assert actual == expected, (
        f"expected_drops drifted from sidecar for {table.table_name!r}.\n"
        f"  sidecar (live): {expected}\n"
        f"  manifest      : {actual}\n"
        "Update data/datasets/<dataset>/expected_drops.yaml to match the "
        "sidecar, or revert the preprocess.py change that caused the drift."
    )


def test_manifest_row_counts_match_sidecar(table: PrimaryTable) -> None:
    """When the sidecar reports raw/cleaned rows, the manifest must agree."""
    manifest_entry = manifest_entry_for(table)
    if manifest_entry is None:
        pytest.skip("manifest missing — covered by test_manifest_entry_exists")
    sidecar = load_sidecar(table)
    if sidecar is None:
        pytest.skip("no sidecar — row counts come from raw file (other test)")

    first = sidecar_first_read_rows(sidecar)
    final = sidecar_final_write_rows(sidecar)
    if first is not None and "raw_rows" in manifest_entry:
        assert manifest_entry["raw_rows"] == first, (
            f"manifest.raw_rows={manifest_entry['raw_rows']} but sidecar "
            f"first read recorded rows={first}"
        )
    if final is not None and "cleaned_rows" in manifest_entry:
        assert manifest_entry["cleaned_rows"] == final, (
            f"manifest.cleaned_rows={manifest_entry['cleaned_rows']} but sidecar "
            f"final write recorded rows={final}"
        )
