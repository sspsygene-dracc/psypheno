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
            self.central_gene_table_links,
            columns=pd.Index(["id", "central_gene_id"]),
        )

    def write_to_sqlite(self, conn: sqlite3.Connection) -> None:
        name = sanitize_identifier(self.link_table_name)
        # WITHOUT ROWID + composite PK on (central_gene_id, id) collapses the
        # heap table and the central_gene_id index into one B-tree. The query
        # pattern is exclusively `WHERE central_gene_id = ?`, so the PK prefix
        # serves the lookup without a separate index.
        conn.execute(
            f"CREATE TABLE [{name}] ("
            "central_gene_id INTEGER NOT NULL, "
            "id INTEGER NOT NULL, "
            "PRIMARY KEY (central_gene_id, id)"
            ") WITHOUT ROWID"
        )
        seen: set[tuple[int, int]] = set()
        rows: list[tuple[int, int]] = []
        for row_id, gene_id in self.central_gene_table_links:
            if gene_id is None:
                continue
            key = (gene_id, row_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(key)
        conn.executemany(
            f"INSERT INTO [{name}] (central_gene_id, id) VALUES (?, ?)",
            rows,
        )

    def get_meta_entry(self) -> str:
        int_is_perturbed = "1" if self.is_perturbed else "0"
        int_is_target = "1" if self.is_target else "0"
        return f"{self.gene_column_name}:{self.link_table_name}:{int_is_perturbed}:{int_is_target}"
