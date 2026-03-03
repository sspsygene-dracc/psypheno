import sqlite3
from dataclasses import dataclass

import pandas as pd

from processing.sql_utils import sanitize_identifier


@dataclass
class LinkTable:
    central_gene_table_links: list[tuple[int, int | None]]
    gene_column_name: str
    link_table_name: str
    is_perturbed: bool
    is_target: bool

    def get_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            self.central_gene_table_links, columns=["id", "central_gene_id"]
        )

    def write_to_sqlite(self, conn: sqlite3.Connection) -> None:
        name = sanitize_identifier(self.link_table_name)
        conn.execute(
            f"CREATE TABLE [{name}] (id INTEGER, central_gene_id INTEGER)"
        )
        conn.executemany(
            f"INSERT INTO [{name}] (id, central_gene_id) VALUES (?, ?)",
            self.central_gene_table_links,
        )

    def get_meta_entry(self) -> str:
        int_is_perturbed = "1" if self.is_perturbed else "0"
        int_is_target = "1" if self.is_target else "0"
        return f"{self.gene_column_name}:{self.link_table_name}:{int_is_perturbed}:{int_is_target}"
