"""Data containers for the combined-p-value pipeline.

These dataclasses describe what flows between stages; nothing here does I/O.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal


# Regulation axis: "any" preserves the legacy behavior (all rows), while
# "up" / "down" filter to rows where the table's effect_column is positive /
# negative before combining.
Regulation = Literal["any", "up", "down"]

# Row from data_tables filtered to (table_name, pvalue_column, link_tables,
# effect_column) — the shape the collection / group-building code consumes.
# `effect_column` is None for tables that did not declare one, which makes the
# table ineligible for the up/down regulation groups.
SourceTableQuad = tuple[str, str, str, str | None]

# Full row from data_tables that drives group enumeration; carries the assay /
# disease / organism keys needed for filtered groups, plus effect_column.
SourceTableRow = tuple[
    str, str, str, str | None, str | None, str | None, str | None
]


@dataclass
class CollectedPvalues:
    """P-values gathered for one compute group, keyed by central_gene_id.

    `per_table` keeps p-values bucketed by source table so the per-gene
    Bonferroni pre-collapse can run per-table; `all_pvalues` is the flat
    list used by methods (Cauchy, HMP) that consume raw p-values directly.
    """

    per_table: defaultdict[int, defaultdict[str, list[float]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list))
    )
    all_pvalues: defaultdict[int, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def is_empty(self) -> bool:
        return not self.all_pvalues

    @classmethod
    def from_dicts(
        cls,
        per_table: dict[int, dict[str, list[float]]],
        all_pvalues: dict[int, list[float]],
    ) -> "CollectedPvalues":
        """Build a CollectedPvalues from plain nested dicts (test convenience)."""
        out = cls()
        for gid, tbl_dict in per_table.items():
            for tbl, pvals in tbl_dict.items():
                out.per_table[gid][tbl] = list(pvals)
        for gid, pvals in all_pvalues.items():
            out.all_pvalues[gid] = list(pvals)
        return out


@dataclass
class GeneCombinedPvalues:
    """Combined-p-value record for one gene as returned by the R script."""

    fisher_p: float | None
    fisher_fdr: float | None
    cauchy_p: float | None
    cauchy_fdr: float | None
    hmp_p: float | None
    hmp_fdr: float | None


# pylint: disable=too-many-instance-attributes
@dataclass
class ComputeGroup:
    """Spec for one pre-computed combined-p-values output table.

    `direction` is always "target" or "perturbed" — every gene_mapping carries
    a direction now, so there is no direction-agnostic mode.

    `regulation` is "any" / "up" / "down". For "up" and "down" the runner
    restricts row collection to rows whose table-declared effect_column is
    positive / negative, and skips tables that have no effect_column.
    """

    tables: list[SourceTableQuad]
    out_table: str
    label: str
    direction: str
    regulation: Regulation = "any"
    assay_filter: str | None = None
    disease_filter: str | None = None
    organism_filter: str | None = None
    use_gene_flags: bool = True
    min_tables: int = 1


# pylint: disable=too-many-instance-attributes
@dataclass
class CollectedGroup:
    """A ComputeGroup paired with its collected p-values, ready for R."""

    pvalues: CollectedPvalues
    out_table: str
    label: str
    direction: str
    regulation: Regulation
    assay_filter: str | None
    disease_filter: str | None
    organism_filter: str | None
    use_gene_flags: bool


@dataclass
class RJobInput:
    """Input to one R meta-analysis job submitted to the thread pool."""

    idx: int
    pvalues: CollectedPvalues
    label: str
