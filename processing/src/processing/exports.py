"""Build the user-facing download artifacts inside the SQLite DB.

After load-db has populated the data tables, `write_exports()` builds:

    export_files                 SQLite table — one row per downloadable file:
        path TEXT PRIMARY KEY,   "tables/foo.tsv", "metadata/foo.yaml",
                                 "preprocessing/foo.yaml", "manifest.tsv",
                                 "ensembl_to_symbol.tsv", "README.txt",
                                 "all-tables.zip"
        content_type TEXT,
        content BLOB,
        last_modified INTEGER    unix epoch
        size INTEGER

The `/api/download/[...path]` Next.js endpoint reads BLOBs from this table
— there is no `exports/` directory on the filesystem and the API never
opens a file by path. The SQLite DB itself is downloaded via a separate
endpoint that streams `SSPSYGENE_DATA_DB`.
"""

import csv
import io
import json
import logging
import os
import re
import sqlite3
import time
import zipfile
from contextlib import closing
from typing import Any, Iterator

import yaml

logger = logging.getLogger(__name__)

# Mirrors web/lib/ensembl-symbol-resolver.ts: standalone or embedded ENSG /
# ENSMUSG / ENSDARG IDs, with optional `.<version>` suffix stripped on lookup.
_ENSG_PATTERN = re.compile(r"\b(ENS(?:MUS|DAR)?G\d+)(?:\.\d+)?\b")


def _load_ensembl_symbol_map(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute(
            "SELECT ensembl_id, symbol FROM ensembl_to_symbol"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {ensg: symbol for ensg, symbol in rows}


def _substitute_ensgs(value: object, symbol_map: dict[str, str]) -> object:
    if not symbol_map or not isinstance(value, str) or "ENS" not in value:
        return value
    if not _ENSG_PATTERN.search(value):
        return value
    return _ENSG_PATTERN.sub(lambda m: symbol_map.get(m.group(1), m.group(0)), value)


def _list_data_tables(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT table_name, short_label, medium_label, long_label, description,
                  gene_columns, gene_species, display_columns, scalar_columns,
                  link_tables, links, categories, source, assay, disease,
                  field_labels, organism, organism_key,
                  publication_first_author, publication_last_author,
                  publication_author_count, publication_authors, publication_year,
                  publication_journal, publication_doi, publication_pmid,
                  publication_sspsygene_grants,
                  pvalue_column, fdr_column, effect_column,
                  preprocessing
           FROM data_tables
           ORDER BY table_name"""
    ).fetchall()
    return list(rows)


def _split_csv(s: str | None) -> list[str]:
    if not s:
        return []
    return [x for x in s.split(",") if x]


def _parse_link_tables(spec: str | None) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    if not spec:
        return out
    for entry in spec.split(","):
        parts = entry.split(":")
        if len(parts) != 3:
            continue
        col, link_name, direction = parts
        if direction not in ("perturbed", "target"):
            continue
        out.append({
            "gene_column": col,
            "link_table": link_name,
            "perturbed_or_target": direction,
        })
    return out


def _parse_json_list(s: str | None) -> list[Any]:
    if not s:
        return []
    try:
        parsed = json.loads(s)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _parse_json_dict(s: str | None) -> dict[Any, Any]:
    if not s:
        return {}
    try:
        parsed = json.loads(s)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _stream_table_rows(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str],
) -> Iterator[tuple[Any, ...]]:
    """Yield `(row, ...)` tuples for the given table.

    Uses a fresh cursor and selects only the requested columns; ordered by
    `id` for deterministic output. The SQL identifiers are validated upstream
    (table name comes from `data_tables.table_name`, columns from
    `display_columns`) and pre-quoted with [] brackets.
    """
    quoted = ", ".join(f"[{c}]" for c in columns)
    cur = conn.cursor()
    cur.execute(f"SELECT {quoted} FROM [{table}] ORDER BY id")
    for row in cur:
        yield row


def _build_table_tsv(
    conn: sqlite3.Connection,
    table_row: sqlite3.Row,
    symbol_map: dict[str, str],
) -> tuple[bytes, int]:
    """Return (tsv-bytes, row-count)."""
    columns = _split_csv(table_row["display_columns"])
    if not columns:
        return b"", 0
    buf = io.StringIO()
    writer = csv.writer(
        buf, delimiter="\t", quoting=csv.QUOTE_MINIMAL, lineterminator="\n"
    )
    writer.writerow(columns)
    count = 0
    for row in _stream_table_rows(conn, table_row["table_name"], columns):
        out_row: list[str] = []
        for cell in row:
            if cell is None:
                out_row.append("")
                continue
            substituted = _substitute_ensgs(cell, symbol_map)
            out_row.append(str(substituted))
        writer.writerow(out_row)
        count += 1
    return buf.getvalue().encode("utf-8"), count


def _table_metadata_dict(table_row: sqlite3.Row) -> dict[str, object]:
    """Reconstruct a per-table metadata dict from the data_tables row.

    Mirrors the original config.yaml per-table entry shape so users see
    something familiar; omits keys that aren't populated.
    """
    md: dict[str, object] = {
        "table": table_row["table_name"],
        "short_label": table_row["short_label"],
        "medium_label": table_row["medium_label"],
        "long_label": table_row["long_label"],
        "description": table_row["description"],
        "source": table_row["source"],
        "organism": table_row["organism"],
        "organism_key": _split_csv(table_row["organism_key"]),
        "assay": _split_csv(table_row["assay"]),
        "disease": _split_csv(table_row["disease"]),
        "categories": _split_csv(table_row["categories"]),
        "links": _parse_json_list(table_row["links"]),
        "gene_species": table_row["gene_species"],
        "gene_columns": _split_csv(table_row["gene_columns"]),
        "display_columns": _split_csv(table_row["display_columns"]),
        "scalar_columns": _split_csv(table_row["scalar_columns"]),
        "field_labels": _parse_json_dict(table_row["field_labels"]),
        "link_tables": _parse_link_tables(table_row["link_tables"]),
        "pvalue_column": table_row["pvalue_column"],
        "fdr_column": table_row["fdr_column"],
        "effect_column": table_row["effect_column"],
    }
    publication: dict[str, object] = {}
    if table_row["publication_first_author"]:
        publication["first_author"] = table_row["publication_first_author"]
    if table_row["publication_last_author"]:
        publication["last_author"] = table_row["publication_last_author"]
    if table_row["publication_author_count"] is not None:
        publication["author_count"] = table_row["publication_author_count"]
    authors = _parse_json_list(table_row["publication_authors"])
    if authors:
        publication["authors"] = authors
    if table_row["publication_year"] is not None:
        publication["year"] = table_row["publication_year"]
    if table_row["publication_journal"]:
        publication["journal"] = table_row["publication_journal"]
    if table_row["publication_doi"]:
        publication["doi"] = table_row["publication_doi"]
    if table_row["publication_pmid"]:
        publication["pmid"] = table_row["publication_pmid"]
    grants = _parse_json_list(table_row["publication_sspsygene_grants"])
    if grants:
        publication["sspsygene_grants"] = grants
    if publication:
        md["publication"] = publication
    return {
        k: v
        for k, v in md.items()
        if v not in (None, "", [], {})
    }


def _build_table_metadata_yaml(table_row: sqlite3.Row) -> bytes:
    md = _table_metadata_dict(table_row)
    return yaml.safe_dump(
        md, sort_keys=False, allow_unicode=True, width=100
    ).encode("utf-8")


def _build_preprocessing_yaml(table_row: sqlite3.Row) -> bytes | None:
    """Per-table preprocessing provenance (#150). Returns None if absent."""
    raw = table_row["preprocessing"]
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        logger.warning(
            "preprocessing JSON for %s is malformed; skipping",
            table_row["table_name"],
        )
        return None
    return yaml.safe_dump(
        parsed, sort_keys=False, allow_unicode=True, width=100
    ).encode("utf-8")


def _build_ensembl_symbol_tsv(conn: sqlite3.Connection) -> tuple[bytes, int]:
    buf = io.StringIO()
    writer = csv.writer(
        buf, delimiter="\t", quoting=csv.QUOTE_MINIMAL, lineterminator="\n"
    )
    writer.writerow(["ensembl_id", "symbol", "central_gene_id", "species"])
    count = 0
    try:
        cur = conn.execute(
            "SELECT ensembl_id, symbol, central_gene_id, species "
            "FROM ensembl_to_symbol ORDER BY ensembl_id"
        )
    except sqlite3.OperationalError:
        return buf.getvalue().encode("utf-8"), 0
    for row in cur:
        writer.writerow(row)
        count += 1
    return buf.getvalue().encode("utf-8"), count


def _build_manifest(
    table_rows: list[sqlite3.Row],
    row_counts: dict[str, int],
) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(
        buf, delimiter="\t", quoting=csv.QUOTE_MINIMAL, lineterminator="\n"
    )
    writer.writerow([
        "table_name",
        "short_label",
        "medium_label",
        "row_count",
        "columns",
        "organism",
        "assay",
        "publication_doi",
        "tsv_path",
        "metadata_path",
        "preprocessing_path",
        "source_links",
    ])
    for r in table_rows:
        tn = r["table_name"]
        writer.writerow([
            tn,
            r["short_label"] or "",
            r["medium_label"] or "",
            row_counts.get(tn, 0),
            ",".join(_split_csv(r["display_columns"])),
            r["organism"] or "",
            r["assay"] or "",
            r["publication_doi"] or "",
            f"tables/{tn}.tsv",
            f"metadata/{tn}.yaml",
            f"preprocessing/{tn}.yaml" if r["preprocessing"] else "",
            ";".join(
                link["url"]
                for link in _parse_json_list(r["links"])
                if isinstance(link, dict) and "url" in link
            ),
        ])
    return buf.getvalue().encode("utf-8")


_README = """\
SSPsyGene Knowledge Base — data export bundle
=============================================

This bundle contains the processed data tables used by https://psypheno.gi.ucsc.edu/.
Gene identifiers have been resolved to gene symbols (HGNC for human, MGI for mouse)
where mappings exist; rows otherwise carry the raw identifier they were loaded with.

Layout
------
  manifest.tsv                Index: one row per data table, with row counts,
                              columns, and pointers to the per-table files.
  tables/{table}.tsv          Full per-table data dump, tab-separated.
  metadata/{table}.yaml       Per-table metadata: description, columns +
                              field labels, source, links, gene mappings,
                              and citation.
  preprocessing/{table}.yaml  Per-table preprocessing provenance: which
                              gene-symbol rescues fired, what was dropped,
                              row counts before/after each step. Only
                              present for tables whose dataset ships a
                              preprocessing.yaml.
  ensembl_to_symbol.tsv       Ensembl ID ↔ gene symbol mapping used by
                              the website.
  README.txt                  This file.

Loading in R
------------
  manifest <- read.delim("manifest.tsv", stringsAsFactors = FALSE)
  tbl      <- read.delim("tables/perturb_fish_astro.tsv", stringsAsFactors = FALSE)
  head(tbl)

Loading in Python (pandas)
--------------------------
  import pandas as pd
  manifest = pd.read_csv("manifest.tsv", sep="\\t")
  tbl      = pd.read_csv("tables/perturb_fish_astro.tsv", sep="\\t")

Citing a dataset
----------------
Each metadata/{table}.yaml file includes the underlying publication block
(first/last author, year, journal, DOI, PMID, SSPsyGene grants). Please cite
the original publication when using a dataset.
"""


# MIME types for the export artifacts. Path extensions are matched in the
# Next.js handler too, but storing them alongside the blob makes the API a
# pure DB lookup with no extension-table duplication.
_MIME_BY_EXT: dict[str, str] = {
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".yaml": "application/x-yaml; charset=utf-8",
    ".yml": "application/x-yaml; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".zip": "application/zip",
}


def _content_type_for(path: str) -> str:
    _, ext = os.path.splitext(path)
    return _MIME_BY_EXT.get(ext.lower(), "application/octet-stream")


def _ensure_export_files_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS export_files;
        CREATE TABLE export_files (
            path TEXT PRIMARY KEY,
            content_type TEXT NOT NULL,
            content BLOB NOT NULL,
            size INTEGER NOT NULL,
            last_modified INTEGER NOT NULL
        ) WITHOUT ROWID;
        """
    )


def _insert_export(
    conn: sqlite3.Connection,
    path: str,
    content: bytes,
    *,
    last_modified: int,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO export_files "
        "(path, content_type, content, size, last_modified) "
        "VALUES (?, ?, ?, ?, ?)",
        (path, _content_type_for(path), content, len(content), last_modified),
    )


def _build_zip_from_blobs(conn: sqlite3.Connection, exclude: set[str]) -> bytes:
    """Build all-tables.zip from the rows already in `export_files`.

    Sorted walk → deterministic byte output run-to-run. Excludes any paths
    in `exclude` (notably itself).
    """
    rows = conn.execute(
        "SELECT path, content FROM export_files ORDER BY path"
    ).fetchall()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for r in rows:
            path = r["path"]
            if path in exclude:
                continue
            zf.writestr(path, r["content"])
    return buf.getvalue()


def write_exports(db_path: object, exports_dir: object | None = None) -> None:
    """Populate `export_files` in the DB at `db_path` with downloadable artifacts.

    `exports_dir` is accepted for back-compat with prior callers but is
    ignored — the export tree no longer lives on the filesystem. Exports
    are stored as BLOBs in the DB and served via the `/api/download` API
    that queries them by path.
    """
    if exports_dir is not None:
        logger.info("exports_dir argument ignored; exports now live in the DB")

    last_modified = int(time.time())

    # Wrap the connection in `closing(...)` so it actually closes when the
    # block exits — sqlite3.Connection.__exit__ only commits/rollbacks the
    # transaction, it does NOT close the connection. Without this wrapper
    # the lock on `db_path` would persist into the WAL-checkpoint step in
    # sq_load.py and trigger "database is locked".
    with closing(sqlite3.connect(str(db_path))) as conn, conn:  # pylint: disable=confusing-with-statement
        conn.row_factory = sqlite3.Row
        symbol_map = _load_ensembl_symbol_map(conn)
        logger.info("Loaded %d ensembl-to-symbol mappings", len(symbol_map))

        _ensure_export_files_table(conn)

        table_rows = _list_data_tables(conn)
        logger.info("Exporting %d data tables", len(table_rows))

        row_counts: dict[str, int] = {}
        preprocessing_count = 0
        for r in table_rows:
            tn = r["table_name"]

            tsv_bytes, row_count = _build_table_tsv(conn, r, symbol_map)
            row_counts[tn] = row_count
            _insert_export(
                conn, f"tables/{tn}.tsv", tsv_bytes, last_modified=last_modified
            )

            metadata_bytes = _build_table_metadata_yaml(r)
            _insert_export(
                conn,
                f"metadata/{tn}.yaml",
                metadata_bytes,
                last_modified=last_modified,
            )

            preprocessing_bytes = _build_preprocessing_yaml(r)
            if preprocessing_bytes is not None:
                _insert_export(
                    conn,
                    f"preprocessing/{tn}.yaml",
                    preprocessing_bytes,
                    last_modified=last_modified,
                )
                preprocessing_count += 1

        logger.info(
            "Wrote preprocessing YAML for %d / %d tables",
            preprocessing_count,
            len(table_rows),
        )

        ensembl_bytes, ensembl_rows = _build_ensembl_symbol_tsv(conn)
        _insert_export(
            conn,
            "ensembl_to_symbol.tsv",
            ensembl_bytes,
            last_modified=last_modified,
        )
        logger.info("Wrote ensembl_to_symbol.tsv with %d rows", ensembl_rows)

        manifest_bytes = _build_manifest(table_rows, row_counts)
        _insert_export(
            conn, "manifest.tsv", manifest_bytes, last_modified=last_modified
        )
        _insert_export(
            conn,
            "README.txt",
            _README.encode("utf-8"),
            last_modified=last_modified,
        )

        # Build all-tables.zip from everything written so far. It excludes
        # itself (would be a chicken-and-egg) and the SQLite DB (downloaded
        # via a separate streaming endpoint).
        zip_bytes = _build_zip_from_blobs(conn, exclude={"all-tables.zip"})
        _insert_export(
            conn, "all-tables.zip", zip_bytes, last_modified=last_modified
        )

        conn.commit()

    logger.info("Exports written to %s as BLOBs in export_files", db_path)
