from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from processing.central_gene_table import get_central_gene_table
from processing.my_logger import get_sspsygene_logger
from processing.preprocessing.helpers import is_non_symbol_identifier
from processing.types.link_table import LinkTable, PerturbedOrTarget


@dataclass
class GeneMapping:
    column_name: str
    species: Literal["human", "mouse"]
    link_table_name: str
    ignore_missing: list[str]
    to_upper: bool
    replace: dict[str, str]
    perturbed_or_target: PerturbedOrTarget
    ignore_empty: bool
    multi_gene_separator: str | None = None

    def __post_init__(self):
        if self.species not in ["human", "mouse"]:
            raise ValueError(f"Invalid species: {self.species}")
        if self.to_upper not in [True, False]:
            raise ValueError(f"Invalid to_upper: {self.to_upper}")
        if self.perturbed_or_target not in ("perturbed", "target"):
            raise ValueError(
                f"Invalid perturbed_or_target: {self.perturbed_or_target!r} "
                f"(must be 'perturbed' or 'target')"
            )
        if not isinstance(self.replace, dict):  # type: ignore
            raise ValueError(f"Invalid replace: {self.replace}")
        for key, value in self.replace.items():
            if not isinstance(key, str) or not isinstance(value, str):  # type: ignore
                raise ValueError(f"Invalid replace: {self.replace}")

    @classmethod
    def from_json(cls, json_data: dict[str, Any]) -> "GeneMapping":
        to_upper = json_data["to_upper"] if "to_upper" in json_data else False
        replace: dict[str, str] = json_data["replace"] if "replace" in json_data else {}
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
        return cls(
            column_name=json_data["column_name"],
            species=json_data["species"],
            link_table_name=json_data["link_table_name"],
            ignore_missing=(
                json_data["ignore_missing"] if "ignore_missing" in json_data else []
            ),
            to_upper=to_upper,
            replace=replace,
            perturbed_or_target=json_data["perturbed_or_target"],
            ignore_empty=(
                json_data["ignore_empty"] if "ignore_empty" in json_data else False
            ),
            multi_gene_separator=json_data.get("multi_gene_separator", None),
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

            # Split multi-gene values into individual genes
            if self.multi_gene_separator:
                gene_values = [g.strip() for g in str(elem).split(self.multi_gene_separator) if g.strip()]
            else:
                gene_values = [elem]

            for gene_val in gene_values:
                if self.to_upper:
                    gene_val = gene_val.upper()
                if gene_val in self.replace:
                    gene_val = self.replace[gene_val]
                if gene_val not in species_map:
                    if gene_val in self.ignore_missing:
                        data_id_to_central_gene_id.append((row_id, None))
                        continue

                    if is_non_symbol_identifier(gene_val) is None:
                        get_sspsygene_logger().warning(
                            "Path %s, column %s, gene %s not in gene maps for species %s; adding manually",
                            in_path,
                            self.column_name,
                            gene_val,
                            self.species,
                        )
                    new_entry = get_central_gene_table().add_species_entry(
                        species=self.species,
                        symbol=gene_val,
                        dataset=primary_table_name,
                    )
                    species_map[gene_val] = [new_entry]
                else:
                    for entry in species_map[gene_val]:
                        data_id_to_central_gene_id.append((row_id, entry.row_id))
                        entry.add_used_name(
                            species=self.species, name=gene_val, dataset_name=primary_table_name
                        )
        link_table_full_name = primary_table_name + "__" + self.link_table_name
        return LinkTable(
            central_gene_table_links=data_id_to_central_gene_id,
            gene_column_name=self.column_name,
            link_table_name=link_table_full_name,
            perturbed_or_target=self.perturbed_or_target,
        )
