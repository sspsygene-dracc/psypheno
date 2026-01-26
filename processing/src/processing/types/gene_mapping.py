from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Literal

import pandas as pd
from processing.central_gene_table import CENTRAL_GENE_TABLE
from processing.my_logger import get_sspsygene_logger
from processing.types.link_table import LinkTable


@dataclass
class GeneMapping:
    column_name: str
    species: Literal["human", "mouse"]
    link_table_name: str
    ignore_missing: list[str]
    to_upper: bool
    replace: dict[str, str]
    is_perturbed: bool
    is_target: bool
    ignore_empty: bool

    def __post_init__(self):
        if self.species not in ["human", "mouse"]:
            raise ValueError(f"Invalid species: {self.species}")
        if self.to_upper not in [True, False]:
            raise ValueError(f"Invalid to_upper: {self.to_upper}")
        if not isinstance(self.replace, dict):  # type: ignore
            raise ValueError(f"Invalid replace: {self.replace}")
        for key, value in self.replace.items():
            if not isinstance(key, str) or not isinstance(value, str):  # type: ignore
                raise ValueError(f"Invalid replace: {self.replace}")

    @classmethod
    def from_json(cls, json_data: dict[str, Any]) -> "GeneMapping":
        to_upper = json_data["to_upper"] if "to_upper" in json_data else False
        replace: dict[str, str] = json_data["replace"] if "replace" in json_data else {}
        return cls(
            column_name=json_data["column_name"],
            species=json_data["species"],
            link_table_name=json_data["link_table_name"],
            ignore_missing=(
                json_data["ignore_missing"] if "ignore_missing" in json_data else []
            ),
            to_upper=to_upper,
            replace=replace,
            is_perturbed=(json_data["is_perturbed"]),
            is_target=json_data["is_target"],
            ignore_empty=(
                json_data["ignore_empty"] if "ignore_empty" in json_data else False
            ),
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
        species_map = CENTRAL_GENE_TABLE.get_species_map(
            species=self.species,
        )
        for row_id, elem in zip(id_column, in_column):
            if self.ignore_empty and (pd.isna(elem) or not elem):
                data_id_to_central_gene_id.append((row_id, None))
                continue
            if self.to_upper:
                elem = elem.upper()
            if elem in self.replace:
                elem = self.replace[elem]
            if elem not in species_map:
                if elem in self.ignore_missing:
                    data_id_to_central_gene_id.append((row_id, None))
                    continue

                # write a regex for this format: AC118555.1 or AC118555.1 or AL512330.1; so A[CL]number.number:
                contig_regex = re.compile(
                    r"^(((C[RU]|F[OP]|AUXG|BX|A[CDFJLP])\d{6}\.\d{1,2})|([UZ]\d{5}\.\d))$"
                )
                if not contig_regex.match(elem):
                    get_sspsygene_logger().warning(
                        "Path %s, column %s, gene %s not in gene maps for species %s; adding manually",
                        in_path,
                        self.column_name,
                        elem,
                        self.species,
                    )
                new_entry = CENTRAL_GENE_TABLE.add_species_entry(
                    species=self.species,
                    symbol=elem,
                    dataset=primary_table_name,
                )
                species_map[elem] = [new_entry]
            else:
                for entry in species_map[elem]:
                    data_id_to_central_gene_id.append((row_id, entry.row_id))
                    entry.add_used_name(
                        species=self.species, name=elem, dataset_name=primary_table_name
                    )
        link_table_full_name = primary_table_name + "__" + self.link_table_name
        return LinkTable(
            central_gene_table_links=data_id_to_central_gene_id,
            gene_column_name=self.column_name,
            link_table_name=link_table_full_name,
            is_perturbed=self.is_perturbed,
            is_target=self.is_target,
        )
