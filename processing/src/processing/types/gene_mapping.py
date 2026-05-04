from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from processing.central_gene_table import get_central_gene_table
from processing.my_logger import get_sspsygene_logger
from processing.preprocessing.helpers import (
    NON_SYMBOL_CATEGORIES,
    is_non_symbol_identifier,
)
from processing.types.link_table import LinkTable, PerturbedOrTarget


_KNOWN_NON_RESOLVING_KEYS = {
    "control_values",
    "record_values",
    "record_patterns",
}

# Retired in the #19 / drop-values-removal work — moved out of config.yaml so
# nothing is silently dropped at load-db time. Migration paths:
#   drop_values → control_values: (perturbation controls), record_values:
#     (unrecognized predicted genes still worth a stub), or .filter_rows()
#     in preprocess.py (placeholders / true row drops, recorded in
#     preprocessing.yaml).
#   drop_patterns → record_patterns: in nearly every case; if the dataset
#     truly wants those rows gone, use .filter_rows() in preprocess.py.
_RETIRED_NON_RESOLVING_KEYS = {"drop_values", "drop_patterns"}

_RETIRED_GENE_MAPPING_KEYS = {"ignore_missing", "replace", "to_upper"}


@dataclass
class NonResolving:
    """Per-mapping policy for values that don't resolve to a known symbol.

    Each bucket has explicit semantics:

      control_values
        Perturbation control labels (`NonTarget1`, `SafeTarget`, `GFP`,
        `Control_ST`, etc.). Create a `central_gene` entry with
        `kind='control'`, link the row, but ensure per-gene aggregates
        (volcano backgrounds, FDR meta-analysis, gene browser) filter
        these out. Searchable via the autocomplete (and the `control`
        keyword surfaces all of them at once).

      record_values / record_patterns
        Create a `manually_added=1` central_gene stub (with
        `kind='gene'`) and link the row; do NOT warn. Use for
        retired-but-still-meaningful symbols (`SGK494`, `GATD3B`) and
        pattern categories that legitimately belong in central_gene but
        cannot be auto-resolved.

    Anything not matched here falls through to the strict default:
    WARN + create stub + link.
    """

    control_values: frozenset[str] = field(default_factory=frozenset)
    record_values: frozenset[str] = field(default_factory=frozenset)
    record_patterns: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        for category in self.record_patterns:
            if category not in NON_SYMBOL_CATEGORIES:
                raise ValueError(
                    f"Unknown non_resolving pattern category: {category!r}. "
                    f"Valid categories: {sorted(NON_SYMBOL_CATEGORIES)}"
                )
        overlap = self.control_values & self.record_values
        if overlap:
            raise ValueError(
                f"non_resolving: values appear in both control_values and "
                f"record_values: {sorted(overlap)}"
            )

    @classmethod
    def from_json(cls, json_data: dict[str, Any]) -> "NonResolving":
        retired = set(json_data.keys()) & _RETIRED_NON_RESOLVING_KEYS
        if retired:
            raise ValueError(
                f"non_resolving: key(s) {sorted(retired)} are no longer "
                "supported. Migration paths: drop_values → control_values "
                "(perturbation controls), record_values (predicted genes "
                "you want kept as stubs), or .filter_rows() in preprocess.py "
                "(placeholders / true row drops, tracked in "
                "preprocessing.yaml). drop_patterns → record_patterns or "
                ".filter_rows() — see docs/wrangler_gene_cleanup.md."
            )
        unknown = set(json_data.keys()) - _KNOWN_NON_RESOLVING_KEYS
        if unknown:
            raise ValueError(
                f"non_resolving: unknown key(s) {sorted(unknown)}. "
                f"Recognized keys: {sorted(_KNOWN_NON_RESOLVING_KEYS)}"
            )
        return cls(
            control_values=frozenset(json_data.get("control_values") or []),
            record_values=frozenset(json_data.get("record_values") or []),
            record_patterns=tuple(json_data.get("record_patterns") or []),
        )

    def classify(
        self, gene_val: str
    ) -> Literal["control", "record", "fallback"]:
        if gene_val in self.control_values:
            return "control"
        if gene_val in self.record_values:
            return "record"
        for category in self.record_patterns:
            if NON_SYMBOL_CATEGORIES[category](gene_val):
                return "record"
        return "fallback"


@dataclass
class GeneMapping:
    column_name: str
    species: Literal["human", "mouse"]
    link_table_name: str
    perturbed_or_target: PerturbedOrTarget
    ignore_empty: bool = False
    multi_gene_separator: str | None = None
    non_resolving: NonResolving = field(default_factory=NonResolving)

    def __post_init__(self):
        if self.species not in ["human", "mouse"]:
            raise ValueError(f"Invalid species: {self.species}")
        if self.perturbed_or_target not in ("perturbed", "target"):
            raise ValueError(
                f"Invalid perturbed_or_target: {self.perturbed_or_target!r} "
                f"(must be 'perturbed' or 'target')"
            )

    @classmethod
    def from_json(cls, json_data: dict[str, Any]) -> "GeneMapping":
        if "is_perturbed" in json_data or "is_target" in json_data:
            raise ValueError(
                f"Gene mapping for column {json_data.get('column_name')!r}: "
                "legacy fields 'is_perturbed'/'is_target' are no longer supported. "
                "Replace with a single 'perturbed_or_target: perturbed|target' field."
            )
        if "perturbed_or_target" not in json_data:
            raise ValueError(
                f"Gene mapping for column {json_data.get('column_name')!r}: "
                "missing required field 'perturbed_or_target' (must be "
                "'perturbed' or 'target')."
            )

        column_name = json_data["column_name"]

        retired = _RETIRED_GENE_MAPPING_KEYS & json_data.keys()
        if retired:
            raise ValueError(
                f"Gene mapping for column {column_name!r}: key(s) {sorted(retired)} "
                "are no longer supported. Migrate to the new 'non_resolving:' "
                "block (drop_values / drop_patterns / record_values / "
                "record_patterns), and move replace/to_upper substitutions into "
                "preprocess.py via clean_gene_column(manual_aliases=...) or a "
                "trivial pandas op."
            )

        non_resolving_block = json_data.get("non_resolving")
        if non_resolving_block is not None:
            non_resolving = NonResolving.from_json(non_resolving_block)
        else:
            non_resolving = NonResolving()

        return cls(
            column_name=column_name,
            species=json_data["species"],
            link_table_name=json_data["link_table_name"],
            perturbed_or_target=json_data["perturbed_or_target"],
            ignore_empty=bool(json_data.get("ignore_empty", False)),
            multi_gene_separator=json_data.get("multi_gene_separator"),
            non_resolving=non_resolving,
        )

    def resolve_to_central_gene_table(
        self,
        primary_table_name: str,
        data: pd.DataFrame,
        in_path: Path,
    ) -> LinkTable:
        assert "id" in data.columns, "id column not found in data"
        assert (
            self.column_name in data.columns
        ), f"table {primary_table_name}, column {self.column_name} not found in data columns {data.columns.tolist()}"
        id_column: list[int] = data["id"].tolist()
        in_column: list[str] = data[self.column_name].tolist()
        data_id_to_central_gene_id: list[tuple[int, int | None]] = []
        species_map = get_central_gene_table().get_species_map(
            species=self.species,
        )
        for row_id, elem in zip(id_column, in_column):
            if self.ignore_empty and (pd.isna(elem) or not elem):
                data_id_to_central_gene_id.append((row_id, None))
                continue

            if self.multi_gene_separator:
                gene_values = [
                    g.strip()
                    for g in str(elem).split(self.multi_gene_separator)
                    if g.strip()
                ]
            else:
                gene_values = [elem]

            for gene_val in gene_values:
                if gene_val in species_map:
                    for entry in species_map[gene_val]:
                        data_id_to_central_gene_id.append((row_id, entry.row_id))
                        entry.add_used_name(
                            species=self.species,
                            name=gene_val,
                            dataset_name=primary_table_name,
                        )
                    continue

                disposition = self.non_resolving.classify(gene_val)

                if disposition == "fallback":
                    category = is_non_symbol_identifier(gene_val)
                    if category is None:
                        get_sspsygene_logger().warning(
                            "Path %s, column %s, gene %s not in gene maps for "
                            "species %s; adding manually",
                            in_path,
                            self.column_name,
                            gene_val,
                            self.species,
                        )
                    else:
                        get_sspsygene_logger().warning(
                            "Path %s, column %s, value %s looks like a "
                            "non-symbol identifier (%s) for species %s but is "
                            "not whitelisted under non_resolving; adding stub. "
                            "Add it to non_resolving.record_patterns to "
                            "silence (or drop the row in preprocess.py).",
                            in_path,
                            self.column_name,
                            gene_val,
                            category,
                            self.species,
                        )
                # All three dispositions create a stub and link the row.
                # Controls get kind='control' so per-gene aggregates can
                # filter them out; record/fallback stay as ordinary genes.
                kind = "control" if disposition == "control" else "gene"
                new_entry = get_central_gene_table().add_species_entry(
                    species=self.species,
                    symbol=gene_val,
                    dataset=primary_table_name,
                    kind=kind,
                )
                species_map[gene_val] = [new_entry]
                data_id_to_central_gene_id.append((row_id, new_entry.row_id))

        link_table_full_name = primary_table_name + "__" + self.link_table_name
        return LinkTable(
            central_gene_table_links=data_id_to_central_gene_id,
            gene_column_name=self.column_name,
            link_table_name=link_table_full_name,
            perturbed_or_target=self.perturbed_or_target,
        )
