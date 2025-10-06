from dataclasses import dataclass
from typing import Any, Literal


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
