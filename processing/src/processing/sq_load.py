import logging
from pathlib import Path
import sqlite3

from processing.central_gene_table import CENTRAL_GENE_TABLE
from processing.new_sqlite3 import NewSqlite3
from processing.types.table_to_process_config import TableToProcessConfig


def create_indexes(conn: sqlite3.Connection, table: str, idx_fields: list[str]) -> None:
    for field in idx_fields:
        print(f"Creating index for {field}")
        sql = f"CREATE INDEX {table}_{field}_idx ON {table} ({field})"
        conn.execute(sql)


def load_gene_tables(
    conn: sqlite3.Connection,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE central_gene (
        id INTEGER PRIMARY KEY,
        human_symbol TEXT,
        human_entrez_gene INTEGER,
        hgnc_id TEXT,
        mouse_symbols TEXT,
        mouse_entrez_genes TEXT,
        human_synonyms TEXT,
        mouse_synonyms TEXT,
        dataset_names TEXT,
        num_datasets INTEGER
        )"""
    )
    cur.execute(
        """CREATE TABLE synonyms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        central_gene_id INTEGER,
        species TEXT,
        synonym TEXT
        )"""
    )
    for entry in CENTRAL_GENE_TABLE.entries:
        if not entry.used:
            continue
        human_synonyms = entry.human_synonyms & entry.used_human_names
        mouse_synonyms = entry.mouse_synonyms & entry.used_mouse_names
        to_insert = (
            entry.row_id,
            entry.human_symbol if entry.human_symbol else None,
            entry.human_entrez_gene.entrez_id if entry.human_entrez_gene else None,
            entry.hgnc_id if entry.hgnc_id else None,
            ",".join(entry.mouse_symbols) if entry.mouse_symbols else None,
            (
                ",".join(str(x.entrez_id) for x in entry.mouse_entrez_genes)
                if entry.mouse_entrez_genes
                else None
            ),
            ",".join(human_synonyms) if entry.human_synonyms else None,
            ",".join(mouse_synonyms) if entry.mouse_synonyms else None,
            ",".join(entry.dataset_names) if entry.dataset_names else None,
            len(entry.dataset_names) if entry.dataset_names else 0,
        )
        cur.execute(
            """INSERT INTO central_gene (
            id, human_symbol, human_entrez_gene, hgnc_id, mouse_symbols, 
            mouse_entrez_genes, human_synonyms, mouse_synonyms, dataset_names, num_datasets) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            to_insert,
        )
        for synonym in human_synonyms:
            cur.execute(
                """INSERT INTO synonyms (
                central_gene_id, species, synonym)
                VALUES (?, ?, ?)""",
                (entry.row_id, "h", synonym),
            )
        for synonym in mouse_synonyms:
            cur.execute(
                """INSERT INTO synonyms (
                central_gene_id, species, synonym)
                VALUES (?, ?, ?)""",
                (entry.row_id, "m", synonym),
            )
    create_indexes(
        conn,
        "central_gene",
        [
            "human_symbol",
            "human_entrez_gene",
            "hgnc_id",
            "mouse_symbols",
            "mouse_entrez_genes",
            "human_synonyms",
            "mouse_synonyms",
            "dataset_names",
        ],
    )
    create_indexes(
        conn,
        "synonyms",
        ["central_gene_id", "species", "synonym"],
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
        description TEXT,
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
        cur.execute(
            """INSERT INTO data_tables (
            table_name, description, gene_columns, 
            gene_species, display_columns, 
            scalar_columns, link_tables)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                table_config.table,
                table_config.description,
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
    create_indexes(
        conn,
        "data_tables",
        ["table_name", "gene_species", "link_tables"],
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
        load_gene_tables(conn)
