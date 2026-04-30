"""Group enumeration for the combined-p-values pipeline.

`ComputeGroupBuilder` turns the source-table catalog into a list of
`ComputeGroup` specs — one per (direction × filter-combination) — that the
runner consumes downstream.
"""

from collections import defaultdict

from .data import ComputeGroup, SourceTableRow, SourceTableTriple


class ComputeGroupBuilder:
    """Enumerates `ComputeGroup` specs from the source-table catalog.

    For each direction ("target", "perturbed") we emit:
      - a global group spanning all source tables
      - one group per assay key
      - one group per disease key
      - one group per organism key
      - one group per (assay, disease) pair
      - one group per (assay, organism) pair
      - one group per (disease, organism) pair
      - one group per (assay, disease, organism) triple

    Filtered groups require ≥2 source tables; the global group has no minimum.
    The final filter — that ≥2 tables actually contribute *in this direction* —
    is applied later, in the runner, since it depends on the master scan.
    """

    def __init__(self, source_tables: list[SourceTableRow]):
        self.source_tables = source_tables

    def build(self) -> list[ComputeGroup]:
        tables_3col: list[SourceTableTriple] = [
            (t[0], t[1], t[2]) for t in self.source_tables
        ]

        assay_to_tables: dict[str, list[SourceTableTriple]] = defaultdict(list)
        disease_to_tables: dict[str, list[SourceTableTriple]] = defaultdict(list)
        organism_to_tables: dict[str, list[SourceTableTriple]] = defaultdict(list)
        ad_combo: dict[tuple[str, str], list[SourceTableTriple]] = defaultdict(list)
        ao_combo: dict[tuple[str, str], list[SourceTableTriple]] = defaultdict(list)
        do_combo: dict[tuple[str, str], list[SourceTableTriple]] = defaultdict(list)
        ado_combo: dict[
            tuple[str, str, str], list[SourceTableTriple]
        ] = defaultdict(list)

        for row in self.source_tables:
            table_name, pvalue_col, link_tables, assay_raw, disease_raw, organism_raw = row
            assay_keys = self._split_keys(assay_raw)
            disease_keys = self._split_keys(disease_raw)
            organism_keys = self._split_keys(organism_raw)
            entry: SourceTableTriple = (table_name, pvalue_col, link_tables)

            for ak in assay_keys:
                assay_to_tables[ak].append(entry)
            for dk in disease_keys:
                disease_to_tables[dk].append(entry)
            for ok in organism_keys:
                organism_to_tables[ok].append(entry)
            for ak in assay_keys:
                for dk in disease_keys:
                    ad_combo[(ak, dk)].append(entry)
            for ak in assay_keys:
                for ok in organism_keys:
                    ao_combo[(ak, ok)].append(entry)
            for dk in disease_keys:
                for ok in organism_keys:
                    do_combo[(dk, ok)].append(entry)
            for ak in assay_keys:
                for dk in disease_keys:
                    for ok in organism_keys:
                        ado_combo[(ak, dk, ok)].append(entry)

        groups: list[ComputeGroup] = []
        for direction in ("target", "perturbed"):
            sfx = direction
            groups.append(ComputeGroup(
                tables=tables_3col,
                out_table=f"gene_combined_pvalues_{sfx}",
                label=f"[{direction}] ",
                direction=direction,
                min_tables=1,
            ))

            for ak in sorted(assay_to_tables.keys()):
                groups.append(ComputeGroup(
                    tables=assay_to_tables[ak],
                    out_table=f"gene_combined_pvalues_{ak}_{sfx}",
                    label=f"[assay={ak}, {direction}] ",
                    direction=direction,
                    assay_filter=ak,
                    min_tables=2,
                ))

            for dk in sorted(disease_to_tables.keys()):
                groups.append(ComputeGroup(
                    tables=disease_to_tables[dk],
                    out_table=f"gene_combined_pvalues_d_{dk}_{sfx}",
                    label=f"[disease={dk}, {direction}] ",
                    direction=direction,
                    disease_filter=dk,
                    min_tables=2,
                ))

            for ok in sorted(organism_to_tables.keys()):
                groups.append(ComputeGroup(
                    tables=organism_to_tables[ok],
                    out_table=f"gene_combined_pvalues_o_{ok}_{sfx}",
                    label=f"[organism={ok}, {direction}] ",
                    direction=direction,
                    organism_filter=ok,
                    min_tables=2,
                ))

            for (ak, dk) in sorted(ad_combo.keys()):
                groups.append(ComputeGroup(
                    tables=ad_combo[(ak, dk)],
                    out_table=f"gene_combined_pvalues_{ak}_d_{dk}_{sfx}",
                    label=f"[assay={ak}, disease={dk}, {direction}] ",
                    direction=direction,
                    assay_filter=ak,
                    disease_filter=dk,
                    min_tables=2,
                ))

            for (ak, ok) in sorted(ao_combo.keys()):
                groups.append(ComputeGroup(
                    tables=ao_combo[(ak, ok)],
                    out_table=f"gene_combined_pvalues_{ak}_o_{ok}_{sfx}",
                    label=f"[assay={ak}, organism={ok}, {direction}] ",
                    direction=direction,
                    assay_filter=ak,
                    organism_filter=ok,
                    min_tables=2,
                ))

            for (dk, ok) in sorted(do_combo.keys()):
                groups.append(ComputeGroup(
                    tables=do_combo[(dk, ok)],
                    out_table=f"gene_combined_pvalues_d_{dk}_o_{ok}_{sfx}",
                    label=f"[disease={dk}, organism={ok}, {direction}] ",
                    direction=direction,
                    disease_filter=dk,
                    organism_filter=ok,
                    min_tables=2,
                ))

            for (ak, dk, ok) in sorted(ado_combo.keys()):
                groups.append(ComputeGroup(
                    tables=ado_combo[(ak, dk, ok)],
                    out_table=f"gene_combined_pvalues_{ak}_d_{dk}_o_{ok}_{sfx}",
                    label=f"[assay={ak}, disease={dk}, organism={ok}, {direction}] ",
                    direction=direction,
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
