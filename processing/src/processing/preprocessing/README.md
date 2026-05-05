# `processing.preprocessing` — preprocessing library for dataset wranglers

Per-dataset wrangler scripts under `data/datasets/*/preprocess.py` build
a **Pipeline** of tracked **Step**s that read a raw input, clean it,
and write the result. A shared **Tracker** records every action into a
sibling `preprocessing.yaml` so downstream users can audit exactly which
manual changes were applied (#149, #150).

Putting cleanup here (rather than as runtime fixups in `load-db`) keeps
`load-db` strict and small, and consolidates edge cases in one place.

## Installation / import

The library lives inside the `processing` package. Run `preprocess.py`
scripts inside the same Python environment used for the CLI (e.g.
`processing/.venv-claude/`) so that `from processing.preprocessing
import ...` resolves.

## Quick start

```python
from pathlib import Path

from processing.preprocessing import (
    GeneSymbolNormalizer,
    EnsemblToSymbolMapper,
    MANUAL_ALIASES_HUMAN,
    Pipeline,
    Tracker,
    copy_file,
)

DIR = Path(__file__).resolve().parent


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()
    ensembl_mapper = EnsemblToSymbolMapper.from_env()

    (
        Pipeline(
            "cleaned.csv",
            tracker=tracker,
            normalizer=normalizer,
            ensembl_mapper=ensembl_mapper,
        )
        .read_csv(DIR / "raw.csv")
        .clean_gene(
            "target_gene",
            species="human",
            excel_demangle=True,
            strip_make_unique=True,
            manual_aliases=MANUAL_ALIASES_HUMAN,
            resolve_via_ensembl_map=True,
        )
        .write_csv(DIR / "cleaned.csv")
        .run()
    )

    # Companion files that need to ship through unchanged still get tracked:
    copy_file(DIR / "patients.tsv", DIR / "patients_cleaned.tsv", tracker=tracker)

    tracker.write(DIR / "preprocessing.yaml")
```

## Public API

### Pipeline + Tracker

* `Pipeline(name, *, tracker, normalizer=None, ensembl_mapper=None)` — one
  pipeline per output table. `name` is the output filename and becomes
  the YAML key for this table's actions.
* `Tracker()` — collects `ActionRecord`s across one or more pipelines.
  Call `tracker.write(path)` at the end to dump `preprocessing.yaml`.
* `copy_file(src, dst, *, tracker)` — pass-through copy for unchanged
  companion files. Records a `copy_file` action.

### Pipeline builder methods (all chainable, all tracked)

| Method | What it does |
|---|---|
| `read_csv(path, sep=",", dtype=str)` | Read CSV/TSV into the pipeline's DataFrame. |
| `read_tsv(path)` | `read_csv(path, sep="\t")`. |
| `from_dataframe(df, label=None)` | Start from an in-memory DataFrame (multi-sheet Excel, etc.). |
| `clean_gene(column, *, species, **flags)` | Resolve & annotate a gene-name column (see below). |
| `dropna(columns)` | Drop rows that are NaN in any listed column. |
| `filter_rows(predicate, *, description)` | Keep rows where `predicate(df)` is True. |
| `rename(mapping)` | Rename columns. |
| `reorder(columns)` | Subset and reorder columns. |
| `drop_columns(columns, errors="raise")` | Remove columns. |
| `transform_column(column, func, *, description)` | Apply `func(series)` to a column. |
| `insert_column(name, value, position=None)` | Insert a constant or computed column. |
| `write_csv(path, sep=",")` / `write_tsv(path)` | Write to disk; finishes the pipeline. |
| `add(step)` | Escape hatch — append any custom `Step`. |

`pipeline.run()` returns the final DataFrame (after `write_*` has
already executed) so you can collect frames for a multi-sheet `concat`.

### `clean_gene` flags

`clean_gene(column, *, species, ...)` wraps the existing
`clean_gene_column()` function. Same flags, same resolution order:

* `resolve_hgnc_id=True` — convert literal `HGNC:NNNNN` IDs to current
  symbols.
* `excel_demangle=True` — `1-Mar`, `9-Sep`, `2023-09-04` → real symbol.
* `strip_make_unique=True` — `MATR3.1` → `MATR3` (guarded).
* `split_symbol_ensg=True` — `TBCE_ENSG00000284770` → `TBCE`.
* `manual_aliases={...}` — last-resort `OLD: NEW` rescue dict.
* `resolve_via_ensembl_map=True` — rescue raw `ENSG…` / `ENSMUSG…` via
  the supplied `ensembl_mapper`.
* `drop_non_symbols=True` — drop rows whose value matches
  `is_non_symbol_identifier`.

The cleaner keeps `<column>_raw` (original value) and
`_<column>_resolution` (per-row tag) in the output by default, so users
can see what happened. If you don't want them in the cleaned file, add
`.drop_columns(["_<column>_resolution"])` (also tracked).

### Free helpers (still available for one-off use)

`clean_gene_column`, `excel_demangle`, `is_non_symbol_identifier`,
`split_symbol_ensg`, `strip_make_unique_suffix`, `GeneSymbolNormalizer`,
`EnsemblToSymbolMapper`, `CleanReport`. See the source for the
underlying classifiers and rescue order; the pipeline `clean_gene` step
is a thin wrapper over `clean_gene_column`.

## Provenance YAML

The sibling `preprocessing.yaml` looks like this:

```yaml
generated: '2026-05-04T10:49:25Z'
inputs:
  - deg.txt
tables:
  deg_cleaned.txt:
    - step: read_csv
      source: deg.txt
      separator: "\t"
      rows: 1627
      columns: [Gene, logFC, ...]
    - step: clean_gene_column
      column: Gene
      species: mouse
      flags: {excel_demangle: true}
      counts: {passed_through: 1622, rescued_excel: 3, unresolved: 2}
      dropped_rows: 0
      sample_unresolved: [Gm16091, Gm42864]
    - step: write_csv
      destination: deg_cleaned.txt
      rows: 1627
      columns: [Gene, logFC, ..., Gene_raw, _Gene_resolution]
```

Tracked in git so PR diffs of `preprocessing.yaml` make every
preprocessing change review-visible. Loaded into the per-table
metadata download by the `load-db` pipeline (follow-up PR).

## Migration guidance for wranglers

If you currently rely on the loader's `to_upper`, `replace`,
`split_column_map`, or `ignore_missing` knobs in `config.yaml`, the
migration path is:

1. Add or extend `data/datasets/<name>/preprocess.py` using `Pipeline`.
2. Build `tracker = Tracker()` once at the top of `main()`.
3. Add steps for each transformation; `clean_gene(...)` for gene-name
   columns, `split_column(...)` for compound identifiers like
   `Foxg1_3` → `(Foxg1, 3)`.
4. Call `tracker.write(DIR / "preprocessing.yaml")` at the end.
5. Drop the corresponding YAML knobs once the migration lands.

`multi_gene_separator` stays in `config.yaml` — it isn't a value
transform, it's a link-table semantic (one displayed row → multiple
`(row_id, central_gene_id)` link tuples, e.g. a CNV row whose
`region_genes` cell lists every gene the CNV affects). Pulling it
into preprocess.py would force one-row-per-gene, breaking the
one-row-per-CNV display.

Issue [#121](https://github.com/sspsygene-dracc/psypheno/issues/121)
tracks the per-dataset migration. Issue
[#149](https://github.com/sspsygene-dracc/psypheno/issues/149) tracks
the OO library refactor; issue
[#150](https://github.com/sspsygene-dracc/psypheno/issues/150) tracks
surfacing provenance to the website.
