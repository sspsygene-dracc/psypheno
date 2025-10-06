import logging
from pathlib import Path
import sqlite3
from typing import Any, cast
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


def split_column(
    df: pd.DataFrame, source_col: str, new_col1: str, new_col2: str, sep: str
) -> pd.DataFrame:
    """
    Split `source_col` into two new columns (`new_col1`, `new_col2`) by `sep`,
    keeping the original column intact.
    """
    parts: Any = cast(
        Any, df[source_col].astype("string").str.split(sep, n=1, expand=True)
    )
    df[new_col1] = parts[0]
    df[new_col2] = parts[1]
    return df


def load_data(
    in_path: Path,
    split_column_map: list[SplitColumnEntry],
    entrez_conversions: list[EntrezConversion],
) -> pd.DataFrame:
    conversion_dict: dict[str, Any] = {
        "convert_string": True,
        "convert_integer": False,
        "convert_boolean": False,
        "convert_floating": False,
    }
    data = pd.read_csv(in_path, sep="\t").convert_dtypes(**conversion_dict)  # type: ignore
    for entry in split_column_map:
        data = split_column(
            data,
            source_col=entry.source_col,
            new_col1=entry.new_col1,
            new_col2=entry.new_col2,
            sep=entry.sep,
        )
    entrez_gene_maps = get_entrez_gene_maps()
    for conversion in entrez_conversions:
        assert (
            conversion.column_name in data.columns
        ), f"Column {conversion.column_name} not found in data columns {data.columns.tolist()}"
        in_column_list: list[str] = data[conversion.column_name].tolist()
        out_data: list[str] = []
        for elem in in_column_list:
            assert (
                elem in entrez_gene_maps[conversion.species]
            ), f"Path {in_path}: gene {elem} not gene maps for species {conversion.species}"
            out_data.append(
                ",".join(
                    str(x.entrez_id) for x in entrez_gene_maps[conversion.species][elem]
                )
            )
        data[conversion.out_column_name] = out_data
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
