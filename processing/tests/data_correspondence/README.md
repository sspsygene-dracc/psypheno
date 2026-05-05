# Data-correspondence tests (#113 / #117)

These tests verify two contracts about every primary dataset:

1. **Row accounting** — every raw-CSV row that didn't make it into the
   SQLite DB is *expected* to be missing. The wrangler ships an
   `expected_drops.yaml` manifest that records the row counts and the
   per-step drop categories; the tests cross-check those counts against
   the live preprocessing sidecars and against the actual CSV / DB on
   disk.

2. **Per-(dataset, gene) value correspondence** — sampled rows survive
   the raw → cleaned → DB chain unchanged, modulo the `clean_gene_column`
   resolution which is allowed to rewrite the gene column (the original
   value lands in `<col>_raw`).

A small meta-analysis spot-check then verifies that the
`gene_combined_pvalues_*` tables agree with what `r_runner.call_r_combine`
recomputes from per-table inputs for a sample of genes.

## Layout

| File | What it does | When it runs |
| --- | --- | --- |
| `helpers.py` | Enumerate primary tables; load sidecars + manifests | always |
| `conftest.py` | Auto-parametrize `table` over every primary table; `db` fixture | always |
| `test_row_accounting.py` | Manifest presence + sidecar internal consistency + manifest-vs-sidecar | CI-friendly (no DB / raw data needed) |
| `test_sidecar_vs_files.py` | Manifest counts == on-disk file rows == DB rows | local; skips per test when artifacts are missing |
| `test_value_correspondence.py` | N=50 random rows: cleaned/raw == DB; raw == cleaned for non-gene cols | `slow`, local |
| `test_meta_analysis_correspondence.py` | Recompute combined p-values for 20 genes via R; compare to DB | `slow`, `requires_r`, local |

## Per-dataset manifest format

`data/datasets/<name>/expected_drops.yaml`:

```yaml
tables:
  sfari_human_genes:
    raw_file: SFARI-Gene_genes_..._export.csv          # the wrangler's input
    cleaned_file: SFARI-Gene_genes_..._cleaned.csv     # what load-db reads
    raw_rows: 1238
    cleaned_rows: 1238
    db_rows: 1238
    pipeline_used: true
    expected_drops:
      - step: clean_gene_column
        column: ensembl-id
        dropped_rows: 0
        counts:
          rescued_ensembl_map: 1225
          passed_through: 13
```

Counts are exact. If a wrangler edits `preprocess.py` and the sidecar
counts shift, `test_manifest_matches_sidecar` fails with a diff. The fix
is one of:

- The change was intentional → update the manifest entry.
- The change was a regression → revert the `preprocess.py` edit.

## First-run / new-dataset workflow

When a new dataset is added (or a new table inside an existing one),
`test_manifest_entry_exists` fails the first time it runs against the
new table:

```
No manifest entry for table 'foo_bar' in foo/expected_drops.yaml.
A proposed entry was derived from the live sidecar/DB and written to
data/datasets/foo/expected_drops.yaml.proposed. Review and merge it
into expected_drops.yaml, then re-run.
```

The `.proposed` file holds an auto-derived entry — counts pulled from
the sidecar (`<cleaned>.preprocessing.yaml`) plus a live `db_rows` count
when `data/db/sspsygene.db` is reachable. The wrangler reviews and
appends it to `expected_drops.yaml` (committing both files), then the
test family passes.

## Running locally

```bash
# Fast tier (CI-friendly): sidecar internal consistency + manifest
# integrity. No DB or raw data required.
pytest processing/tests/data_correspondence/test_row_accounting.py -v

# Add raw-file and DB checks (still fast). Set SSPSYGENE_DATA_DIR if
# you're running in a worktree without a local data/ payload.
SSPSYGENE_DATA_DIR=/path/to/main/sspsygene/data \
  pytest processing/tests/data_correspondence/ -v

# Slow tier: cell-level value spot-check + R meta-analysis.
SSPSYGENE_DATA_DIR=/path/to/main/sspsygene/data \
  pytest processing/tests/data_correspondence/ -v -m slow
```

The `slow` and `requires_r` markers are registered in
`processing/pyproject.toml`. Tests use deterministic random seeds
(`SEED = 20260505`) so failures are reproducible.

## Why manifests aren't auto-computed every run

The manifest is the *contract* — what the wrangler claims is true about
the dataset. Auto-deriving the same numbers from the live sidecar would
make the test vacuous. Instead, the test compares the live sidecar /
files / DB against the committed manifest, so any drift between code
and contract surfaces as a failure.
