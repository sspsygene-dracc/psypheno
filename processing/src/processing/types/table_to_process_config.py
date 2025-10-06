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

    @classmethod
    def from_json(cls, json_data: dict[str, Any]) -> "TableToProcessConfig":
        return cls(
            table=json_data["table"],
            in_path=json_data["in_path"],
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
