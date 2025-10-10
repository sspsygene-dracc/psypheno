from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from processing.entrez_gene_maps import get_entrez_gene_maps
from processing.my_logger import get_sspsygene_logger
from processing.sq_load import LinkTable
from processing.types.entrez_gene import EntrezGene


@dataclass
class EntrezConversion:
    column_name: str
    species: Literal["human", "mouse", "zebrafish"]
    link_table_name: str
    ignore_missing: list[str]
    to_upper: bool
    replace: dict[str, str]

    def __post_init__(self):
        if self.species not in ["human", "mouse", "zebrafish"]:
            raise ValueError(f"Invalid species: {self.species}")
        if self.to_upper not in [True, False]:
            raise ValueError(f"Invalid to_upper: {self.to_upper}")
        if not isinstance(self.replace, dict):  # type: ignore
            raise ValueError(f"Invalid replace: {self.replace}")
        for key, value in self.replace.items():
            if not isinstance(key, str) or not isinstance(value, str):  # type: ignore
                raise ValueError(f"Invalid replace: {self.replace}")

    @classmethod
    def from_json(cls, json_data: dict[str, Any]) -> "EntrezConversion":
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
        )

    def resolve_entrez_genes(
        self,
        primary_table_name: str,
        data: pd.DataFrame,
        in_path: Path,
        used_entrez_ids: set[EntrezGene],
    ) -> LinkTable:
        assert "id" in data.columns, "id column not found in data"
        orig_maps = get_entrez_gene_maps()
        species_map = orig_maps[self.species].get_map()
        assert (
            self.column_name in data.columns
        ), f"Column {self.column_name} not found in data columns {data.columns.tolist()}"
        id_column: list[int] = data["id"].tolist()
        in_column: list[str] = data[self.column_name].tolist()
        entrez_id_map: list[tuple[int, EntrezGene]] = []
        for row_id, elem in zip(id_column, in_column):
            if self.to_upper:
                elem = elem.upper()
            if elem in self.replace:
                elem = self.replace[elem]
            if elem not in species_map:
                if elem not in self.ignore_missing:
                    get_sspsygene_logger().warning(
                        "Path %s, column %s, gene %s not in gene maps for species %s",
                        in_path,
                        self.column_name,
                        elem,
                        self.species,
                    )
                entrez_id_map.append((row_id, EntrezGene(-2)))
            else:
                used_entrez_ids.update(species_map[elem])
                for entrez_gene in species_map[elem]:
                    entrez_id_map.append((row_id, entrez_gene))
        link_table_full_name = primary_table_name + "__" + self.link_table_name
        return LinkTable(
            links=entrez_id_map,
            gene_column_name=self.column_name,
            link_table_name=link_table_full_name,
        )
