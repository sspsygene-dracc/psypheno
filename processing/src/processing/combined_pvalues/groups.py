"""Group enumeration for the combined-p-values pipeline.

`ComputeGroupBuilder` turns the source-table catalog into a list of
`ComputeGroup` specs — one per (direction × regulation × filter-combination) —
that the runner consumes downstream.
"""

from collections import defaultdict
from typing import get_args

from .data import (
    ComputeGroup,
    Regulation,
    SourceTableQuad,
    SourceTableRow,
)


# All regulation modes enumerated by the builder. "any" preserves the legacy
# behavior; "up"/"down" produce new sibling tables filtered by effect-size
# sign at row collection time.
_REGULATIONS: tuple[Regulation, ...] = get_args(Regulation)


def _reg_suffix(regulation: Regulation) -> str:
    """Output-table-name suffix for a regulation. Empty for 'any' so existing
    `gene_combined_pvalues_target` etc. names stay unchanged."""
    return "" if regulation == "any" else f"_{regulation}"


def _reg_label(regulation: Regulation) -> str:
    """Human-readable label fragment used in click.echo progress output."""
    return "" if regulation == "any" else f", reg={regulation}"


class ComputeGroupBuilder:
    """Enumerates `ComputeGroup` specs from the source-table catalog.

    For each (direction ∈ {target, perturbed}) × (regulation ∈ {any, up, down})
    we emit:
      - a global group spanning all source tables
      - one group per assay key
      - one group per disease key
      - one group per organism key
      - one group per (assay, disease) pair
      - one group per (assay, organism) pair
      - one group per (disease, organism) pair
      - one group per (assay, disease, organism) triple

    Filtered groups require ≥2 source tables; the global group has no minimum.
    Under "up" / "down" regulation, tables without an effect_column are
    pre-filtered out — if a filter combination ends up with <2 tables that
    declare an effect_column, that group is skipped at enumeration time. The
    final filter — that ≥2 tables actually contribute *in this direction* —
    is applied later, in the runner, since it depends on the master scan.
    """

    def __init__(self, source_tables: list[SourceTableRow]):
        self.source_tables = source_tables

    def build(self) -> list[ComputeGroup]:
        tables_4col: list[SourceTableQuad] = [
            (t[0], t[1], t[2], t[6]) for t in self.source_tables
        ]

        # Per-key bucketing for global; up/down filter out tables with no
        # effect_column since those rows can never satisfy a sign filter.
        bucketed: dict[Regulation, _Buckets] = {
            reg: _build_buckets(self.source_tables, reg) for reg in _REGULATIONS
        }

        groups: list[ComputeGroup] = []
        for direction in ("target", "perturbed"):
            sfx_dir = direction
            for regulation in _REGULATIONS:
                rsfx = _reg_suffix(regulation)
                rlbl = _reg_label(regulation)
                buckets = bucketed[regulation]

                # Global tables list adapts to regulation: "any" uses every
                # source table; up/down use only those with an effect_column.
                global_tables: list[SourceTableQuad]
                if regulation == "any":
                    global_tables = tables_4col
                else:
                    global_tables = [
                        t for t in tables_4col if t[3]  # effect_column declared
                    ]
                if global_tables:
                    groups.append(ComputeGroup(
                        tables=global_tables,
                        out_table=f"gene_combined_pvalues_{sfx_dir}{rsfx}",
                        label=f"[{direction}{rlbl}] ",
                        direction=direction,
                        regulation=regulation,
                        min_tables=1,
                    ))

                for ak in sorted(buckets.assay.keys()):
                    groups.append(ComputeGroup(
                        tables=buckets.assay[ak],
                        out_table=f"gene_combined_pvalues_{ak}_{sfx_dir}{rsfx}",
                        label=f"[assay={ak}, {direction}{rlbl}] ",
                        direction=direction,
                        regulation=regulation,
                        assay_filter=ak,
                        min_tables=2,
                    ))

                for dk in sorted(buckets.disease.keys()):
                    groups.append(ComputeGroup(
                        tables=buckets.disease[dk],
                        out_table=f"gene_combined_pvalues_d_{dk}_{sfx_dir}{rsfx}",
                        label=f"[disease={dk}, {direction}{rlbl}] ",
                        direction=direction,
                        regulation=regulation,
                        disease_filter=dk,
                        min_tables=2,
                    ))

                for ok in sorted(buckets.organism.keys()):
                    groups.append(ComputeGroup(
                        tables=buckets.organism[ok],
                        out_table=f"gene_combined_pvalues_o_{ok}_{sfx_dir}{rsfx}",
                        label=f"[organism={ok}, {direction}{rlbl}] ",
                        direction=direction,
                        regulation=regulation,
                        organism_filter=ok,
                        min_tables=2,
                    ))

                for (ak, dk) in sorted(buckets.ad.keys()):
                    groups.append(ComputeGroup(
                        tables=buckets.ad[(ak, dk)],
                        out_table=(
                            f"gene_combined_pvalues_{ak}_d_{dk}_{sfx_dir}{rsfx}"
                        ),
                        label=f"[assay={ak}, disease={dk}, {direction}{rlbl}] ",
                        direction=direction,
                        regulation=regulation,
                        assay_filter=ak,
                        disease_filter=dk,
                        min_tables=2,
                    ))

                for (ak, ok) in sorted(buckets.ao.keys()):
                    groups.append(ComputeGroup(
                        tables=buckets.ao[(ak, ok)],
                        out_table=(
                            f"gene_combined_pvalues_{ak}_o_{ok}_{sfx_dir}{rsfx}"
                        ),
                        label=f"[assay={ak}, organism={ok}, {direction}{rlbl}] ",
                        direction=direction,
                        regulation=regulation,
                        assay_filter=ak,
                        organism_filter=ok,
                        min_tables=2,
                    ))

                for (dk, ok) in sorted(buckets.do.keys()):
                    groups.append(ComputeGroup(
                        tables=buckets.do[(dk, ok)],
                        out_table=(
                            f"gene_combined_pvalues_d_{dk}_o_{ok}_{sfx_dir}{rsfx}"
                        ),
                        label=(
                            f"[disease={dk}, organism={ok}, "
                            f"{direction}{rlbl}] "
                        ),
                        direction=direction,
                        regulation=regulation,
                        disease_filter=dk,
                        organism_filter=ok,
                        min_tables=2,
                    ))

                for (ak, dk, ok) in sorted(buckets.ado.keys()):
                    groups.append(ComputeGroup(
                        tables=buckets.ado[(ak, dk, ok)],
                        out_table=(
                            f"gene_combined_pvalues_{ak}_d_{dk}_"
                            f"o_{ok}_{sfx_dir}{rsfx}"
                        ),
                        label=(
                            f"[assay={ak}, disease={dk}, organism={ok}, "
                            f"{direction}{rlbl}] "
                        ),
                        direction=direction,
                        regulation=regulation,
                        assay_filter=ak,
                        disease_filter=dk,
                        organism_filter=ok,
                        min_tables=2,
                    ))

        return groups

    @staticmethod
    def _split_keys(raw: str | None) -> list[str]:
        """Split a comma-separated, possibly-None key string into trimmed parts."""
        if not raw:
            return []
        return [k.strip() for k in raw.split(",") if k.strip()]


# pylint: disable=too-many-instance-attributes
class _Buckets:
    """Per-(assay/disease/organism × combinations) source-table buckets."""

    def __init__(self) -> None:
        self.assay: dict[str, list[SourceTableQuad]] = defaultdict(list)
        self.disease: dict[str, list[SourceTableQuad]] = defaultdict(list)
        self.organism: dict[str, list[SourceTableQuad]] = defaultdict(list)
        self.ad: dict[tuple[str, str], list[SourceTableQuad]] = defaultdict(list)
        self.ao: dict[tuple[str, str], list[SourceTableQuad]] = defaultdict(list)
        self.do: dict[tuple[str, str], list[SourceTableQuad]] = defaultdict(list)
        self.ado: dict[
            tuple[str, str, str], list[SourceTableQuad]
        ] = defaultdict(list)


def _build_buckets(
    source_tables: list[SourceTableRow],
    regulation: Regulation,
) -> _Buckets:
    """Bucket source tables by assay/disease/organism keys + their combos.

    Under up/down, tables without an effect_column are dropped — they could
    never contribute to a sign-filtered combine.
    """
    buckets = _Buckets()
    for row in source_tables:
        (
            table_name,
            pvalue_col,
            link_tables,
            assay_raw,
            disease_raw,
            organism_raw,
            effect_col,
        ) = row
        if regulation != "any" and not effect_col:
            continue
        assay_keys = ComputeGroupBuilder._split_keys(assay_raw)
        disease_keys = ComputeGroupBuilder._split_keys(disease_raw)
        organism_keys = ComputeGroupBuilder._split_keys(organism_raw)
        entry: SourceTableQuad = (table_name, pvalue_col, link_tables, effect_col)

        for ak in assay_keys:
            buckets.assay[ak].append(entry)
        for dk in disease_keys:
            buckets.disease[dk].append(entry)
        for ok in organism_keys:
            buckets.organism[ok].append(entry)
        for ak in assay_keys:
            for dk in disease_keys:
                buckets.ad[(ak, dk)].append(entry)
        for ak in assay_keys:
            for ok in organism_keys:
                buckets.ao[(ak, ok)].append(entry)
        for dk in disease_keys:
            for ok in organism_keys:
                buckets.do[(dk, ok)].append(entry)
        for ak in assay_keys:
            for dk in disease_keys:
                for ok in organism_keys:
                    buckets.ado[(ak, dk, ok)].append(entry)
    return buckets
