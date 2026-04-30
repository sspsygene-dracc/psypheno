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

from .data import (
    CollectedGroup,
    CollectedPvalues,
    ComputeGroup,
    GeneCombinedPvalues,
    RJobInput,
)
from .flags import (
    FLAG_GENE_GROUPS,
    FLAG_LOCUS_GROUPS,
    GeneFlagger,
    _load_hgnc_gene_flags,
    _load_nimh_priority_genes,
    _load_tf_list,
)
from .collection import (
    _collect_pvalues_for_tables,
    _filter_collected,
    _parse_link_tables_for_direction,
    _precollapse,
)
from .r_runner import (
    _call_r_combine,
    _ensure_r_packages,
    _parse_r_results,
    _r_lib_setup_code,
    _write_r_inputs,
)
from .groups import ComputeGroupBuilder
from .writer import _write_combined_results
from .runner import MetaAnalysisRun, compute_combined_pvalues

__all__ = [
    "CollectedGroup",
    "CollectedPvalues",
    "ComputeGroup",
    "ComputeGroupBuilder",
    "FLAG_GENE_GROUPS",
    "FLAG_LOCUS_GROUPS",
    "GeneCombinedPvalues",
    "GeneFlagger",
    "MetaAnalysisRun",
    "RJobInput",
    "compute_combined_pvalues",
]
