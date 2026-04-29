"""Build the user-facing download artifacts after the SQLite DB is ready.

Drops a self-contained `exports/` tree next to the DB:

    exports/
      tables/{table}.tsv          # full data-table dump, ENSG→symbol applied
      metadata/{table}.yaml       # per-table metadata sidecar
      ensembl_to_symbol.tsv       # closes #99
      manifest.tsv                # one row per data table (counts, columns, …)
      README.txt                  # short orientation + R snippet
      all-tables.zip              # everything above (sans the SQLite copy)
      sspsygene.db                # copy of the built SQLite

Atomic install via tmp-dir + rename so a concurrent web request can't observe
a half-written tree.
"""

import csv
import json
import logging
import os
import re
import shutil
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
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
                  pvalue_column, fdr_column, effect_column
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
        if len(parts) != 4:
            continue
        col, link_name, perturbed, target = parts
        out.append({
            "gene_column": col,
            "link_table": link_name,
            "is_perturbed": perturbed == "1",
            "is_target": target == "1",
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
    """Yield (row_count, row) tuples for the given table.

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


def _write_table_tsv(
    conn: sqlite3.Connection,
    table_row: sqlite3.Row,
    out_path: Path,
    symbol_map: dict[str, str],
) -> int:
    columns = _split_csv(table_row["display_columns"])
    if not columns:
        out_path.write_text("")
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(
            f, delimiter="\t", quoting=csv.QUOTE_MINIMAL, lineterminator="\n"
        )
        writer.writerow(columns)
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
    return count


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
        "links": _split_csv(table_row["links"]),
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
    # Drop keys whose value is None / empty list / empty dict to keep the YAML
    # tidy. Empty collections in particular would otherwise render as `[]`/`{}`
    # alongside the ones with real content.
    return {
        k: v
        for k, v in md.items()
        if v not in (None, "", [], {})
    }


def _write_table_metadata_yaml(table_row: sqlite3.Row, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    md = _table_metadata_dict(table_row)
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(md, f, sort_keys=False, allow_unicode=True, width=100)


def _write_ensembl_symbol_tsv(
    conn: sqlite3.Connection, out_path: Path
) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        cur = conn.execute(
            "SELECT ensembl_id, symbol, central_gene_id, species "
            "FROM ensembl_to_symbol ORDER BY ensembl_id"
        )
    except sqlite3.OperationalError:
        out_path.write_text("ensembl_id\tsymbol\tcentral_gene_id\tspecies\n")
        return 0
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(
            f, delimiter="\t", quoting=csv.QUOTE_MINIMAL, lineterminator="\n"
        )
        writer.writerow(["ensembl_id", "symbol", "central_gene_id", "species"])
        for row in cur:
            writer.writerow(row)
            count += 1
    return count


def _write_manifest(
    table_rows: list[sqlite3.Row],
    row_counts: dict[str, int],
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(
            f, delimiter="\t", quoting=csv.QUOTE_MINIMAL, lineterminator="\n"
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
                r["links"] or "",
            ])


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


def _write_readme(out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_README, encoding="utf-8")


def _build_zip(staging: Path, zip_path: Path, exclude: set[str]) -> None:
    """ZIP everything in `staging` except files whose relative path is in `exclude`."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # Sorted walk → deterministic byte output run-to-run.
        for root, dirs, files in os.walk(staging):
            dirs.sort()
            for name in sorted(files):
                full = Path(root) / name
                rel = str(full.relative_to(staging))
                if rel in exclude:
                    continue
                zf.write(full, arcname=rel)


def write_exports(db_path: Path, exports_dir: Path | None = None) -> None:
    """Build the export tree from the freshly-built DB at `db_path`.

    Writes to a sibling tmp directory and then atomically renames into place,
    so a concurrent web fetch can't observe a half-written tree.
    """
    if exports_dir is None:
        exports_dir = db_path.parent / "exports"
    exports_dir.parent.mkdir(parents=True, exist_ok=True)

    # Build into a sibling tmp dir on the same filesystem so the final rename
    # is atomic. Manual lifecycle (not TemporaryDirectory) because we need to
    # rename the dir out from under ourselves on success.
    tmp = exports_dir.with_name(exports_dir.name + ".new")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    try:
        logger.info("Writing exports to staging dir %s", tmp)

        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
            symbol_map = _load_ensembl_symbol_map(conn)
            logger.info("Loaded %d ensembl-to-symbol mappings", len(symbol_map))

            table_rows = _list_data_tables(conn)
            logger.info("Exporting %d data tables", len(table_rows))

            row_counts: dict[str, int] = {}
            for r in table_rows:
                tn = r["table_name"]
                tsv_path = tmp / "tables" / f"{tn}.tsv"
                yaml_path = tmp / "metadata" / f"{tn}.yaml"
                row_counts[tn] = _write_table_tsv(conn, r, tsv_path, symbol_map)
                _write_table_metadata_yaml(r, yaml_path)

            ensembl_count = _write_ensembl_symbol_tsv(
                conn, tmp / "ensembl_to_symbol.tsv"
            )
            logger.info("Wrote ensembl_to_symbol.tsv with %d rows", ensembl_count)

            _write_manifest(table_rows, row_counts, tmp / "manifest.tsv")
            _write_readme(tmp / "README.txt")

        # Build the all-tables.zip from everything written so far.
        _build_zip(
            tmp,
            tmp / "all-tables.zip",
            exclude={"sspsygene.db", "all-tables.zip"},
        )

        # Hardlink the SQLite DB if possible (cheap, zero copy, snapshots the
        # current inode so a subsequent atomic-rename rebuild doesn't mutate
        # the exported copy). Fall back to a full copy across filesystems.
        sqlite_target = tmp / "sspsygene.db"
        try:
            os.link(db_path, sqlite_target)
        except OSError:
            shutil.copy2(db_path, sqlite_target)

        # Atomic swap. Rename existing exports/ aside (if any), rename tmp
        # into its slot, then remove the aside. Window of inconsistency is
        # the gap between the two renames — effectively zero on POSIX.
        old_aside = exports_dir.with_name(exports_dir.name + ".old")
        if old_aside.exists():
            shutil.rmtree(old_aside)
        if exports_dir.exists():
            os.rename(exports_dir, old_aside)
        os.rename(tmp, exports_dir)
        if old_aside.exists():
            shutil.rmtree(old_aside)
    finally:
        # If we errored before the rename, tear down the tmp dir so we don't
        # leak it. After a successful rename, tmp no longer exists.
        if tmp.exists():
            shutil.rmtree(tmp)

    logger.info("Exports written to %s", exports_dir)
