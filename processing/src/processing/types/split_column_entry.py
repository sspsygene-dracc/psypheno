from dataclasses import dataclass
from typing import Any


@dataclass
class SplitColumnEntry:
    source_col: str
    new_col1: str
    new_col2: str
    sep: str

    @classmethod
    def from_json(cls, json_data: dict[str, Any]) -> "SplitColumnEntry":
        return cls(
            source_col=json_data["source_col"],
            new_col1=json_data["new_col1"],
            new_col2=json_data["new_col2"],
            sep=json_data["sep"],
        )
