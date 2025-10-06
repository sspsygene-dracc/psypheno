from dataclasses import dataclass


@dataclass
class SplitColumnEntry:
    source_col: str
    new_col1: str
    new_col2: str
    sep: str