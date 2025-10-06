from dataclasses import dataclass
from typing import Any, cast

import pandas as pd


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

    def split_column(self, df: pd.DataFrame) -> None:
        """
        Split `source_col` into two new columns (`new_col1`, `new_col2`) by `sep`,
        keeping the original column intact.
        """
        parts: Any = cast(
            Any,
            df[self.source_col].astype("string").str.split(self.sep, n=1, expand=True),
        )
        df[self.new_col1] = parts[0]
        df[self.new_col2] = parts[1]
