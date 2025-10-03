from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any
import logging


class NewSqlite3:
    def __init__(self, final_path: Path, logger: logging.Logger):
        self.loggger = logger
        self._conn: sqlite3.Connection | None = None
        self._cursor: sqlite3.Cursor | None = None
        self.final_path: Path = final_path

    def __enter__(self) -> NewSqlite3:
        self._conn = sqlite3.connect(f"file:{self.final_path}?mode=rwc", uri=True)
        self._cursor = self._conn.cursor()
        self._cursor.execute("PRAGMA journal_mode=WAL")
        self._cursor.execute("PRAGMA synchronous=NORMAL")
        self._cursor.execute("PRAGMA cache_size=-100000")  # 100 MB cache
        self._cursor.execute("PRAGMA temp_store=MEMORY")
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        assert self.final_path is not None
        if self._conn is not None:
            self._conn.commit()
        if self._cursor is not None:
            self.loggger.info("Optimizing sqlite3 at %s", self.final_path)
            self._cursor.execute("PRAGMA optimize")
            self.loggger.info("Done optimizing sqlite3 at %s", self.final_path)
            self._cursor.close()
        if self._conn is not None:
            self._conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise ValueError("Connection not set")
        return self._conn

    @property
    def cursor(self) -> sqlite3.Cursor:
        if self._cursor is None:
            raise ValueError("Cursor not set")
        return self._cursor
