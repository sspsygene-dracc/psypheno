from dataclasses import dataclass
import logging
from pathlib import Path
import sqlite3
from typing import Any, Literal
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


def get_sql_friendly_columns(df: pd.DataFrame) -> list[str]:
    return list(
        df.columns.str.lower()
        .str.replace(r"[^a-z0-9_]", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
    )


@dataclass
class DataLoadResult:
    data: pd.DataFrame
    gene_columns: list[str]
    gene_species: Literal["human", "mouse", "zebrafish"]
    display_columns: list[str]
    scalar_columns: list[str]


def load_data(
    in_path: Path,
    split_columns: list[SplitColumnEntry],
    entrez_conversions: list[EntrezConversion],
) -> DataLoadResult:
    conversion_dict: dict[str, Any] = {
        "convert_string": True,
        "convert_integer": False,
        "convert_boolean": False,
        "convert_floating": False,
    }
    data = pd.read_csv(in_path, sep="\t").convert_dtypes(**conversion_dict)
    display_columns = get_sql_friendly_columns(data)
    for split_column in split_columns:
        split_column.split_column(data)
    species_list: list[Literal["human", "mouse", "zebrafish"]] = []
    gene_columns: list[str] = []
    for conversion in entrez_conversions:
        gene_columns.append(conversion.column_name.lower())
        gene_columns.append(conversion.out_column_name.lower())
        species_list.append(conversion.species)
        conversion.resolve_entrez_genes(data, in_path)
    species_set: set[Literal["human", "mouse", "zebrafish"]] = set(species_list)
    assert len(species_set) == 1, "No or multiple species in the same table: " + str(
        species_list
    )
    species = species_set.pop()
    data.columns = get_sql_friendly_columns(data)
    scalar_columns: list[str] = [
        x
        for x in display_columns
        if data[x].dtype == "float64" and x not in set(gene_columns)
    ]
    return DataLoadResult(
        data=data,
        gene_columns=gene_columns,
        gene_species=species,
        display_columns=display_columns,
        scalar_columns=scalar_columns,
    )


def load_entrez_conversions(conn: sqlite3.Connection) -> None:
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


def load_data_tables(
    conn: sqlite3.Connection, table_configs: list[TableToProcessConfig]
) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE data_tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        table_name TEXT,
        gene_columns TEXT,
        gene_species TEXT,
        display_columns TEXT,
        scalar_columns TEXT)"""
    )
    for table_config in table_configs:
        data_and_meta = load_data(
            table_config.in_path,
            table_config.split_column_map,
            table_config.entrez_conversions,
        )
        data_and_meta.data.to_sql(
            table_config.table, conn, if_exists="replace", index=False
        )
        create_indexes(conn, table_config.table, table_config.index_fields)
        cur.execute(
            """INSERT INTO data_tables (
            table_name, gene_columns, gene_species, display_columns, scalar_columns)
            VALUES (?, ?, ?, ?, ?)""",
            (
                table_config.table,
                ",".join(data_and_meta.gene_columns),
                data_and_meta.gene_species,
                ",".join(data_and_meta.display_columns),
                ",".join(data_and_meta.scalar_columns),
            ),
        )
    cur.execute("CREATE INDEX data_tables_table_idx ON data_tables (table_name)")
    cur.execute(
        "CREATE INDEX data_tables_gene_species_idx ON data_tables (gene_species)"
    )
    conn.commit()


def load_db(db_name: Path, table_configs: list[TableToProcessConfig]) -> None:
    logger = logging.getLogger(__name__)
    db_name.parent.mkdir(parents=True, exist_ok=True)
    db_wal = db_name.parent / (db_name.name + "-wal")
    db_wal.unlink(missing_ok=True)
    db_shm = db_name.parent / (db_name.name + "-shm")
    db_shm.unlink(missing_ok=True)
    db_name.unlink(missing_ok=True)
    with NewSqlite3(db_name, logger) as new_sqlite3:
        conn = new_sqlite3.conn
        load_data_tables(conn, table_configs)
        load_entrez_conversions(conn)
