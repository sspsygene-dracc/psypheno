from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from processing.entrez_gene_maps import get_entrez_gene_maps
from processing.my_logger import get_sspsygene_logger


@dataclass
class EntrezConversion:
    column_name: str
    species: Literal["human", "mouse", "zebrafish"]
    out_column_name: str
    ignore_missing: list[str]

    def __post_init__(self):
        if self.species not in ["human", "mouse", "zebrafish"]:
            raise ValueError(f"Invalid species: {self.species}")

    @classmethod
    def from_json(cls, json_data: dict[str, Any]) -> "EntrezConversion":
        return cls(
            column_name=json_data["column_name"],
            species=json_data["species"],
            out_column_name=json_data["out_column_name"],
            ignore_missing=(
                json_data["ignore_missing"] if "ignore_missing" in json_data else []
            ),
        )

    def resolve_entrez_genes(self, data: pd.DataFrame, in_path: Path) -> None:
        entrez_gene_maps = get_entrez_gene_maps()
        assert (
            self.column_name in data.columns
        ), f"Column {self.column_name} not found in data columns {data.columns.tolist()}"
        in_column_list: list[str] = data[self.column_name].tolist()
        out_data: list[str] = []
        for elem in in_column_list:
            if elem not in entrez_gene_maps[self.species]:
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
                out_data.append(
                    ",".join(
                        str(x.entrez_id) for x in entrez_gene_maps[self.species][elem]
                    )
                )
        data[self.out_column_name] = out_data
