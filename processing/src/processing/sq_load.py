import logging
import sqlite3

from processing.new_sqlite3 import NewSqlite3


def create_indexes(conn: sqlite3.Connection, table: str, idx_fields: list[str]) -> None:
    for field in idx_fields:
        print(f"Creating index for {field}")
        sql = f"CREATE INDEX {table}_{field}_idx ON {table} ({field})"
        conn.execute(sql)


def load_db(
    table: str,
    use_fields: list[str],
    index_fields: list[str],
    int_fields: list[str],
    float_fields: list[str],
    db_name: str,
    in_fname: str,
) -> None:
    logger = logging.getLogger(__name__)
    with NewSqlite3(db_name, logger) as new_sqlite3:
        load_rows(conn, table, rows, use_fields, int_fields, float_fields)
        create_indexes(conn, table, index_fields)
