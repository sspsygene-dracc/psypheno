# `processing.preprocessing` — gene-name cleanup library

A small Python library that per-dataset wrangler scripts call from
`data/datasets/*/preprocess.py` to clean gene-symbol columns *before*
the data is consumed by `sspsygene load-db`. Putting the cleanup here
(rather than as runtime fixups in the loader) keeps `load-db` strict
and small, and consolidates edge cases in one place.

## Installation / import

The library lives inside the `processing` package. Run
`preprocess.py` scripts inside the same Python environment used for the
CLI (e.g. `processing/.venv-claude/`) so that `from processing.preprocessing
import ...` resolves.

## Public API

```python
from processing.preprocessing import (
    GeneSymbolNormalizer,
    clean_gene_column,
    excel_demangle,
    is_non_symbol_identifier,
    split_symbol_ensg,
    strip_make_unique_suffix,
)
```

* `GeneSymbolNormalizer.from_env()` — reads `SSPSYGENE_DATA_DIR` and
  loads `homology/hgnc_complete_set.txt` + `homology/MGI_EntrezGene.rpt`.
  Use `from_paths(hgnc_file, mgi_file)` if you need explicit paths.
* `normalizer.resolve(name, species)` — returns the canonical approved
  symbol, or `None` if `name` is not a known symbol/alias/prev_symbol.
* `normalizer.resolve_hgnc_id("HGNC:18790")` — returns the current
  symbol for an HGNC ID literal.

The pure helpers handle one rescue category each:

* `excel_demangle` — `1-Mar`, `9-Sep`, `2023-09-04` → real symbol.
* `is_non_symbol_identifier` — classify ENSG, ENSMUSG, contig,
  GENCODE clone, GenBank accession.
* `strip_make_unique_suffix` — `MATR3.1` → `MATR3` (guarded).
* `split_symbol_ensg` — `TBCE_ENSG00000284770` → `("TBCE", "ENSG00000284770")`.

For most callers, `clean_gene_column(df, column, species=..., normalizer=..., ...)`
is the right entry point: it threads the helpers above into one pass
over a column and emits a `_<column>_resolution` annotation column plus
a `CleanReport` summary. Available rescue flags:

* `resolve_hgnc_id=True` — convert literal `HGNC:NNNNN` IDs to current
  symbols (Tier C1).
* `excel_demangle=True` — Tier A.
* `strip_make_unique=True` — Tier C2.
* `split_symbol_ensg=True` — Tier C3.
* `drop_non_symbols=True` — drop rows whose value matches
  `is_non_symbol_identifier` (Tier B silencing at preprocessing time).

## Migration guidance for wranglers

If you currently rely on the loader's `to_upper`, `multi_gene_separator`,
`replace`, or `ignore_missing` knobs in `config.yaml`, the migration path
is:

1. Add or extend `data/datasets/<name>/preprocess.py`.
2. Build a normalizer once (`GeneSymbolNormalizer.from_env()`).
3. Call `clean_gene_column(...)` on each gene-name column with the
   relevant rescue flags enabled.
4. Drop the corresponding YAML knobs once the migration lands.

Issue [#121](https://github.com/sspsygene-dracc/psypheno/issues/121) tracks
the per-dataset migration; this library only provides the building
blocks.
