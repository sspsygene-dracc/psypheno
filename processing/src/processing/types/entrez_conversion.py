from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from processing.entrez_gene_maps import get_entrez_gene_maps


@dataclass
class EntrezConversion:
    column_name: str
    species: Literal["human", "mouse", "zebrafish"]
    out_column_name: str

    def __post_init__(self):
        if self.species not in ["human", "mouse", "zebrafish"]:
            raise ValueError(f"Invalid species: {self.species}")

    @classmethod
    def from_json(cls, json_data: dict[str, Any]) -> "EntrezConversion":
        return cls(
            column_name=json_data["column_name"],
            species=json_data["species"],
            out_column_name=json_data["out_column_name"],
        )

    def resolve_entrez_genes(self, data: pd.DataFrame, in_path: Path) -> None:
        entrez_gene_maps = get_entrez_gene_maps()
        assert (
            self.column_name in data.columns
        ), f"Column {self.column_name} not found in data columns {data.columns.tolist()}"
        in_column_list: list[str] = data[self.column_name].tolist()
        out_data: list[str] = []
        for elem in in_column_list:
            assert (
                elem in entrez_gene_maps[self.species]
            ), f"Path {in_path}: gene {elem} not gene maps for species {self.species}"
            out_data.append(
                ",".join(str(x.entrez_id) for x in entrez_gene_maps[self.species][elem])
            )
        data[self.out_column_name] = out_data
