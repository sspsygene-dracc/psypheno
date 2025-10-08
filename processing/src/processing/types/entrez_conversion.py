from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from processing.entrez_gene_maps import get_entrez_gene_maps
from processing.my_logger import get_sspsygene_logger
from processing.types.entrez_gene import EntrezGene


@dataclass
class EntrezConversion:
    column_name: str
    species: Literal["human", "mouse", "zebrafish"]
    out_column_name: str
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
            out_column_name=json_data["out_column_name"],
            ignore_missing=(
                json_data["ignore_missing"] if "ignore_missing" in json_data else []
            ),
            to_upper=to_upper,
            replace=replace,
        )

    def resolve_entrez_genes(
        self, data: pd.DataFrame, in_path: Path
    ) -> set[EntrezGene]:
        rv: set[EntrezGene] = set()
        orig_maps = get_entrez_gene_maps()
        species_map = orig_maps[self.species].get_map()
        assert (
            self.column_name in data.columns
        ), f"Column {self.column_name} not found in data columns {data.columns.tolist()}"
        in_column_list: list[str] = data[self.column_name].tolist()
        out_data: list[str] = []
        for elem in in_column_list:
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
                out_data.append("-2")
            else:
                rv.update(species_map[elem])
                out_data.append(",".join(str(x.entrez_id) for x in species_map[elem]))
        data[self.out_column_name] = out_data
        return rv
