from dataclasses import dataclass
from pathlib import Path
from typing import Any

from processing.types.entrez_conversion import EntrezConversion
from processing.types.split_column_entry import SplitColumnEntry


@dataclass
class TableToProcessConfig:
    table: str
    in_path: Path
    split_column_map: list[SplitColumnEntry]
    index_fields: list[str]
    entrez_conversions: list[EntrezConversion]

    def __post_init__(self):
        num_perturbed = 0
        num_target = 0
        for entrez_conversion in self.entrez_conversions:
            if entrez_conversion.is_perturbed:
                num_perturbed += 1
            if entrez_conversion.is_target:
                num_target += 1
        if num_perturbed > 1:
            raise ValueError(
                f"table {self.table}: A table cannot have more than one perturbed entrez conversion"
            )
        if num_target > 1:
            raise ValueError(
                f"table {self.table}: A table cannot have more than one target entrez conversion"
            )
        if num_perturbed != num_target:
            raise ValueError(
                f"table {self.table}: A table must have exactly one perturbed and one target entrez conversion, or none"
            )
        assert (num_perturbed == 0 and num_target == 0) or (
            num_perturbed == 1 and num_target == 1
        ), f"for table {self.table}: num_perturbed: {num_perturbed}, num_target: {num_target}"

    @classmethod
    def from_json(
        cls, json_data: dict[str, Any], base_dir: Path
    ) -> "TableToProcessConfig":
        return cls(
            table=json_data["table"],
            in_path=base_dir / json_data["in_path"],
            split_column_map=[
                SplitColumnEntry.from_json(split_column_map)
                for split_column_map in json_data["split_column_map"]
            ],
            index_fields=json_data["index_fields"],
            entrez_conversions=[
                EntrezConversion.from_json(entrez_conversion)
                for entrez_conversion in json_data["entrez_conversions"]
            ],
        )
