import sqlite3
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from processing.sql_utils import sanitize_identifier


PerturbedOrTarget = Literal["perturbed", "target"]


@dataclass
class LinkTable:
    central_gene_table_links: list[tuple[int, int | None]]
    gene_column_name: str
    link_table_name: str
    perturbed_or_target: PerturbedOrTarget

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
        # 3-part: "col:link:direction" (direction is "perturbed" or "target").
        return f"{self.gene_column_name}:{self.link_table_name}:{self.perturbed_or_target}"
