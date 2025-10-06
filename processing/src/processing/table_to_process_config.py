from dataclasses import dataclass
from pathlib import Path

from processing.split_column_entry import SplitColumnEntry


@dataclass
class TableToProcessConfig:
    table: str
    in_path: Path
    split_column_map: list[SplitColumnEntry]
    index_fields: list[str]
