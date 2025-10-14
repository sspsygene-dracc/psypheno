import logging
from pathlib import Path
import sqlite3

from processing.entrez_gene_maps import get_entrez_gene_maps
from processing.new_sqlite3 import NewSqlite3
from processing.types.entrez_gene import EntrezGene
from processing.types.table_to_process_config import TableToProcessConfig


def create_indexes(conn: sqlite3.Connection, table: str, idx_fields: list[str]) -> None:
    for field in idx_fields:
        print(f"Creating index for {field}")
        sql = f"CREATE INDEX {table}_{field}_idx ON {table} ({field})"
        conn.execute(sql)


def load_entrez_conversions(
    conn: sqlite3.Connection, used_entrez_ids: set[EntrezGene]
) -> None:
    entrez_conversions = get_entrez_gene_maps()
    cur = conn.cursor()
    for species, entrez_gene_map in entrez_conversions.items():
        # create table:
        cur.execute(
            f"""CREATE TABLE {species}_entrez_gene (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT,
            is_symbol INTEGER,
            entrez_id INTEGER)"""
        )
        for entrez_gene_entry in entrez_gene_map.entrez_gene_entries:
            if entrez_gene_entry.entrez_id.entrez_id < 0:
                continue
            if entrez_gene_entry.entrez_id not in used_entrez_ids:
                continue
            cur.execute(
                f"""INSERT INTO {species}_entrez_gene (name, is_symbol, entrez_id) VALUES (?, ?, ?)""",
                (
                    entrez_gene_entry.name,
                    entrez_gene_entry.is_symbol,
                    entrez_gene_entry.entrez_id.entrez_id,
                ),
            )
        cur.execute(
            f"CREATE INDEX {species}_entrez_gene_name_idx ON {species}_entrez_gene (name)"
        )
        cur.execute(
            f"CREATE INDEX {species}_entrez_gene_is_symbol_idx ON {species}_entrez_gene (is_symbol)"
        )
        cur.execute(
            f"CREATE INDEX {species}_entrez_gene_entrez_id_idx ON {species}_entrez_gene (entrez_id)"
        )
    conn.commit()


def load_data_tables(
    conn: sqlite3.Connection, table_configs: list[TableToProcessConfig]
) -> set[EntrezGene]:
    rv: set[EntrezGene] = set()
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE data_tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        table_name TEXT,
        gene_columns TEXT,
        gene_species TEXT,
        display_columns TEXT,
        scalar_columns TEXT,
        link_tables TEXT)"""
    )
    for table_config in table_configs:
        data_and_meta = table_config.load_data_table()
        data_and_meta.data.to_sql(
            table_config.table, conn, if_exists="replace", index=False
        )
        for link_table in data_and_meta.link_tables:
            link_table.get_df().to_sql(
                link_table.link_table_name, conn, if_exists="replace", index=False
            )
        assert "id" in data_and_meta.data.columns, "id column not found in data"
        rv.update(data_and_meta.used_entrez_ids)
        create_indexes(conn, table_config.table, table_config.index_fields)
        cur.execute(
            """INSERT INTO data_tables (
            table_name, gene_columns, gene_species, display_columns, scalar_columns, 
            link_tables)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                table_config.table,
                ",".join(data_and_meta.gene_columns),
                data_and_meta.gene_species,
                ",".join(data_and_meta.display_columns),
                ",".join(data_and_meta.scalar_columns),
                ",".join(
                    link_table.get_meta_entry()
                    for link_table in data_and_meta.link_tables
                ),
            ),
        )
    cur.execute("CREATE INDEX data_tables_table_idx ON data_tables (table_name)")
    cur.execute(
        "CREATE INDEX data_tables_gene_species_idx ON data_tables (gene_species)"
    )
    conn.commit()
    return rv


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
        used_entrez_ids = load_data_tables(conn, table_configs)
        load_entrez_conversions(conn, used_entrez_ids=used_entrez_ids)
