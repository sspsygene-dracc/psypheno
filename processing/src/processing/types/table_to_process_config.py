from dataclasses import dataclass
from pathlib import Path

from processing.types.entrez_conversion import EntrezConversion
from processing.types.split_column_entry import SplitColumnEntry



@dataclass
class TableToProcessConfig:
    table: str
    in_path: Path
    split_column_map: list[SplitColumnEntry]
    index_fields: list[str]
    entrez_conversions: list[EntrezConversion]
