from dataclasses import dataclass
from typing import Literal


@dataclass
class EntrezConversion:
    column_name: str
    species: Literal["human", "mouse", "zebrafish"]
    out_column_name: str

    def __post_init__(self):
        if self.species not in ["human", "mouse", "zebrafish"]:
            raise ValueError(f"Invalid species: {self.species}")
