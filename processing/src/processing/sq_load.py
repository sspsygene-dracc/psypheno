import logging
from pathlib import Path
import sqlite3
from typing import Any
import pandas as pd

from processing.entrez_gene_maps import get_entrez_gene_maps
from processing.new_sqlite3 import NewSqlite3
from processing.types.entrez_conversion import EntrezConversion
from processing.types.split_column_entry import SplitColumnEntry
from processing.types.table_to_process_config import TableToProcessConfig


def create_indexes(conn: sqlite3.Connection, table: str, idx_fields: list[str]) -> None:
    for field in idx_fields:
        print(f"Creating index for {field}")
        sql = f"CREATE INDEX {table}_{field}_idx ON {table} ({field})"
        conn.execute(sql)


def sql_friendly_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = (
        df.columns.str.lower()
        .str.replace(r"[^a-z0-9_]", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
        .str.strip("_")
    )
    return df


def load_data(
    in_path: Path,
    split_columns: list[SplitColumnEntry],
    entrez_conversions: list[EntrezConversion],
) -> pd.DataFrame:
    conversion_dict: dict[str, Any] = {
        "convert_string": True,
        "convert_integer": False,
        "convert_boolean": False,
        "convert_floating": False,
    }
    data = pd.read_csv(in_path, sep="\t").convert_dtypes(**conversion_dict)
    for split_column in split_columns:
        split_column.split_column(data)
    for conversion in entrez_conversions:
        conversion.resolve_entrez_genes(data, in_path)
    data = sql_friendly_columns(data)
    return data


def load_db(db_name: Path, table_configs: list[TableToProcessConfig]) -> None:
    logger = logging.getLogger(__name__)
    with NewSqlite3(db_name, logger) as new_sqlite3:
        conn = new_sqlite3.conn
        for table_config in table_configs:
            data = load_data(
                table_config.in_path,
                table_config.split_column_map,
                table_config.entrez_conversions,
            )
            data.to_sql(table_config.table, conn, if_exists="replace", index=False)
            create_indexes(conn, table_config.table, table_config.index_fields)

        entrez_conversions = get_entrez_gene_maps()
        cur = conn.cursor()
        for species, entrez_gene_map in entrez_conversions.items():
            # create table:
            cur.execute(
                f"""CREATE TABLE {species}_entrez_gene (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                symbol TEXT,
                entrez_id INTEGER)"""
            )
            for symbol, entrez_genes in entrez_gene_map.items():
                for entrez_gene in entrez_genes:
                    cur.execute(
                        f"""INSERT INTO {species}_entrez_gene (symbol, entrez_id) VALUES (?, ?)""",
                        (symbol, entrez_gene.entrez_id),
                    )
            cur.execute(
                f"CREATE INDEX {species}_entrez_gene_symbol_idx ON {species}_entrez_gene (symbol)"
            )
            cur.execute(
                f"CREATE INDEX {species}_entrez_gene_entrez_id_idx ON {species}_entrez_gene (entrez_id)"
            )
        conn.commit()
