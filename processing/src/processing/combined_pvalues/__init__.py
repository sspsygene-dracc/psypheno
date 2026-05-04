"""Compute combined p-values per gene across all datasets.

Statistical computation is delegated to R via subprocess, using reference
implementations from the poolr, ACAT, and harmonicmeanp packages. Python
handles data collection from SQLite, pre-collapse, HGNC gene flags, and
writing results back to SQLite.

Methods:
- Fisher's method: combines -2*sum(ln(p)) with pre-collapsed per-table p-values
- Stouffer's method: converts to Z-scores with pre-collapsed per-table p-values
- Cauchy combination test (CCT): robust to correlated p-values, uses all raw p-values
- Harmonic mean p-value (HMP): Landau-calibrated, robust to dependency, all raw p-values

Module layout:
- `data` — dataclasses + type aliases describing what flows between stages
- `flags` — `GeneFlagger`, HGNC / TF / NIMH reference-data loaders
- `collection` — SQLite p-value collection, link-table parsing, pre-collapse
- `r_runner` — Rscript discovery, package install, input/output CSV bridging
- `groups` — `ComputeGroupBuilder` (per-direction × per-filter group enumeration)
- `writer` — per-group output-table creation + insert
- `runner` — `MetaAnalysisRun` orchestrator + the public `compute_combined_pvalues`

Public callable: `compute_combined_pvalues(conn, …)`. The remaining
re-exports below preserve the historical import surface used by the test
suite.
"""
