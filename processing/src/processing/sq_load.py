import datetime
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import click
import yaml

from processing.central_gene_table import get_central_gene_table
from processing.combined_pvalues.runner import compute_combined_pvalues
from processing.ensembl_symbol_table import compute_ensembl_to_symbol
from processing.exports import write_exports
from processing.gene_descriptions import copy_gene_descriptions
from processing.my_logger import get_sspsygene_logger
from processing.new_sqlite3 import NewSqlite3
from processing.overview_matrix import materialize_overview_matrix
from processing.sql_utils import sanitize_identifier
from processing.types.table_to_process_config import (
    TableToProcessConfig,
    resolve_column_headers,
)


def create_indexes(
    conn: sqlite3.Connection, table: str, idx_fields: list[str], *, skip: bool = False
) -> None:
    if skip:
        return
    table = sanitize_identifier(table)
    log = get_sspsygene_logger()
    for field in idx_fields:
        field = sanitize_identifier(field)
        log.info("  index: %s(%s)", table, field)
        sql = f"CREATE INDEX {table}_{field}_idx ON {table} ({field})"
        conn.execute(sql)


# Default tooltips for pipeline-generated companion columns from
# clean_gene_column. The /gene-parser docs page (#147) explains the
# resolution pipeline and the meaning of each resolution tag.
_RAW_COLUMN_DEFAULT_TOOLTIP = (
    "Original identifier from the source data, before gene-symbol "
    "resolution by the sspsygene pipeline. The resolved symbol is "
    "shown in the corresponding non-_raw column. See /gene-parser "
    "for how raw values are mapped to symbols."
)
_RESOLUTION_COLUMN_DEFAULT_TOOLTIP = (
    "How the displayed gene symbol was derived from the source value "
    "(e.g. hgnc_approved, rescued_ensembl_map, unresolved). Internal "
    "pipeline tag — see /gene-parser for tag meanings."
)


# Columns that need case-insensitive indexes for autocomplete search
_NOCASE_INDEXES: dict[str, list[str]] = {
    "central_gene": ["human_symbol"],
    "extra_mouse_symbols": ["symbol"],
    "extra_gene_synonyms": ["synonym"],
}


def create_nocase_indexes(
    conn: sqlite3.Connection, table: str, *, skip: bool = False
) -> None:
    if skip:
        return
    table = sanitize_identifier(table)
    log = get_sspsygene_logger()
    for field in _NOCASE_INDEXES.get(table, []):
        field = sanitize_identifier(field)
        idx_name = f"{table}_{field}_nocase_idx"
        log.info("  index: %s(%s COLLATE NOCASE)", table, field)
        conn.execute(f"CREATE INDEX {idx_name} ON {table} ({field} COLLATE NOCASE)")


def load_gene_tables(
    conn: sqlite3.Connection,
    *,
    no_index: bool = False,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE central_gene (
        id INTEGER PRIMARY KEY,
        human_symbol TEXT,
        human_entrez_gene INTEGER,
        hgnc_id TEXT,
        mouse_symbols TEXT,
        mouse_mgi_accession_ids TEXT,
        mouse_ensembl_genes TEXT,
        human_synonyms TEXT,
        mouse_synonyms TEXT,
        dataset_names TEXT,
        num_datasets INTEGER,
        manually_added BOOLEAN,
        kind TEXT NOT NULL DEFAULT 'gene'
        )"""
    )
    cur.execute(
        """CREATE TABLE extra_gene_synonyms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        central_gene_id INTEGER,
        species TEXT,
        synonym TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE extra_mouse_symbols (
        id INTEGER PRIMARY KEY,
        symbol TEXT,
        central_gene_id INTEGER
        )"""
    )
    for entry in get_central_gene_table().entries:
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
                ",".join(str(x.mgi_accession_id) for x in entry.mouse_mgi_accession_ids)
                if entry.mouse_mgi_accession_ids
                else None
            ),
            (
                ",".join(str(x) for x in entry.mouse_ensembl_genes)
                if entry.mouse_ensembl_genes
                else None
            ),
            ",".join(human_synonyms) if entry.human_synonyms else None,
            ",".join(mouse_synonyms) if entry.mouse_synonyms else None,
            ",".join(entry.dataset_names) if entry.dataset_names else None,
            len(entry.dataset_names) if entry.dataset_names else 0,
            entry.manually_added,
            entry.kind,
        )
        cur.execute(
            """INSERT INTO central_gene (
            id, human_symbol, human_entrez_gene, hgnc_id, mouse_symbols,
            mouse_mgi_accession_ids, mouse_ensembl_genes, human_synonyms, mouse_synonyms, dataset_names, num_datasets, manually_added, kind)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            to_insert,
        )
        for synonym in human_synonyms:
            cur.execute(
                """INSERT INTO extra_gene_synonyms (
                central_gene_id, species, synonym)
                VALUES (?, ?, ?)""",
                (entry.row_id, "h", synonym),
            )
        for mouse_synonym in entry.mouse_synonyms:
            cur.execute(
                """INSERT INTO extra_gene_synonyms (
                central_gene_id, species, synonym)
                VALUES (?, ?, ?)""",
                (entry.row_id, "m", mouse_synonym),
            )
        for mouse_symbol in entry.mouse_symbols:
            cur.execute(
                """INSERT INTO extra_mouse_symbols (
                central_gene_id, symbol)
                VALUES (?, ?)""",
                (entry.row_id, mouse_symbol),
            )
    create_indexes(
        conn,
        "central_gene",
        [
            "human_symbol",
            "human_entrez_gene",
            "hgnc_id",
            "mouse_symbols",
            "mouse_mgi_accession_ids",
            "mouse_ensembl_genes",
            "human_synonyms",
            "mouse_synonyms",
            "dataset_names",
            "manually_added",
            "kind",
        ],
        skip=no_index,
    )
    create_nocase_indexes(conn, "central_gene", skip=no_index)
    create_indexes(
        conn,
        "extra_gene_synonyms",
        ["central_gene_id", "species", "synonym"],
        skip=no_index,
    )
    create_nocase_indexes(conn, "extra_gene_synonyms", skip=no_index)
    create_indexes(
        conn,
        "extra_mouse_symbols",
        ["symbol", "central_gene_id"],
        skip=no_index,
    )
    create_nocase_indexes(conn, "extra_mouse_symbols", skip=no_index)
    conn.commit()


def _load_preprocessing_for_table(in_path: Path) -> dict[str, object] | None:
    """Read the per-output sidecar `<in_path>.preprocessing.yaml`.

    `in_path` is the cleaned-data file referenced from config.yaml; its
    sidecar (#158) documents every action a wrangler's preprocess.py
    applied to produce it. Returns a dict shaped for storage on the
    data_tables row, or None if no sidecar exists.
    """
    sidecar = in_path.parent / (in_path.name + ".preprocessing.yaml")
    if not sidecar.exists():
        return None
    try:
        loaded = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        logging.getLogger(__name__).warning(
            "preprocessing sidecar at %s is not valid YAML; skipping", sidecar
        )
        return None
    if not isinstance(loaded, dict):
        return None
    actions = loaded.get("actions")
    if not actions:
        return None
    return {
        "generated": loaded.get("generated"),
        "inputs": loaded.get("inputs", []),
        "source_file": in_path.name,
        "actions": actions,
    }


def load_data_tables(
    conn: sqlite3.Connection,
    table_configs: list[TableToProcessConfig],
    skip_missing: bool = False,
    *,
    no_index: bool = False,
    test_central_gene_ids: set[int] | None = None,
    column_header_tokens: dict[str, str] | None = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE data_tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT,
        short_label TEXT,
        medium_label TEXT,
        long_label TEXT,
        description TEXT,
        gene_columns TEXT,
        gene_species TEXT,
        display_columns TEXT,
        scalar_columns TEXT,
        link_tables TEXT,
        links TEXT,
        categories TEXT,
        source TEXT,
        assay TEXT,
        condition TEXT,
        field_labels TEXT,
        column_labels TEXT,
        organism TEXT,
        organism_key TEXT,
        publication_first_author TEXT,
        publication_last_author TEXT,
        publication_author_count INTEGER,
        publication_authors TEXT,
        publication_year INTEGER,
        publication_journal TEXT,
        publication_doi TEXT,
        publication_pmid TEXT,
        publication_sspsygene_grants TEXT,
        pvalue_column TEXT,
        fdr_column TEXT,
        effect_column TEXT,
        include_in_meta_analysis INTEGER NOT NULL DEFAULT 1,
        why_excluded_from_meta_analysis TEXT,
        include_in_overview_matrix INTEGER NOT NULL DEFAULT 0,
        expand_in_overview_matrix INTEGER NOT NULL DEFAULT 0,
        preprocessing TEXT)"""
    )
    log = get_sspsygene_logger()
    loaded: list[str] = []
    skipped: list[str] = []
    for table_config in table_configs:
        if not table_config.in_path.exists():
            if skip_missing:
                click.echo(
                    click.style(
                        f"Warning: Skipping table '{table_config.table}': "
                        f"file not found: {table_config.in_path}",
                        fg="yellow",
                        bold=True,
                    )
                )
                skipped.append(table_config.table)
                continue
            else:
                click.echo(
                    click.style(
                        f"Error: File not found for table '{table_config.table}': "
                        f"{table_config.in_path}\n"
                        "Hint: use --skip-missing-datasets to skip missing files.",
                        fg="red",
                        bold=True,
                    ),
                    err=True,
                )
                sys.exit(1)
        log.info(
            "Loading table %s from %s",
            table_config.table,
            table_config.in_path.name,
        )
        data_and_meta = table_config.load_data_table(
            test_central_gene_ids=test_central_gene_ids,
        )
        loaded.append(table_config.table)
        data_and_meta.data.to_sql(
            table_config.table, conn, if_exists="replace", index=False
        )
        for link_table in data_and_meta.link_tables:
            link_table.write_to_sqlite(conn)
            # No separate index — the WITHOUT ROWID PRIMARY KEY (central_gene_id, id)
            # in LinkTable.write_to_sqlite already serves `WHERE central_gene_id = ?`.
        assert "id" in data_and_meta.data.columns, "id column not found in data"
        create_indexes(conn, table_config.table, ["id"], skip=no_index)

        # Only store field labels for columns that actually exist in the table
        display_col_set = set(data_and_meta.display_columns)
        filtered_field_labels = {
            k: v for k, v in table_config.field_labels.items() if k in display_col_set
        }

        # Auto-inject default tooltips for pipeline-generated companion
        # columns from clean_gene_column. Per-table YAML wins (we only inject
        # when a label isn't already set), and we gate on the base column
        # being present so unrelated columns ending in "_raw" aren't tagged.
        for col in display_col_set:
            if col in filtered_field_labels:
                continue
            if col.endswith("_raw") and col[: -len("_raw")] in display_col_set:
                filtered_field_labels[col] = _RAW_COLUMN_DEFAULT_TOOLTIP
            elif col.startswith("_") and col.endswith("_resolution"):
                base = col[1 : -len("_resolution")]
                if base in display_col_set:
                    filtered_field_labels[col] = _RESOLUTION_COLUMN_DEFAULT_TOOLTIP

        # Resolve display headers for the actual columns (#210): per-table
        # columnLabels overrides win, else the global per-token acronym map is
        # applied; only non-trivial entries are stored (see resolve_column_headers).
        filtered_column_labels = resolve_column_headers(
            display_col_set,
            table_config.column_labels,
            column_header_tokens or {},
        )

        preprocessing_dict = _load_preprocessing_for_table(table_config.in_path)
        # Column -> value, paired by name. Named placeholders (`:col`) are
        # generated from the keys below, so adding/removing a column is a
        # one-line dict edit — no counting a long row of positional `?`.
        row = {
            "table_name": table_config.table,
            "short_label": table_config.short_label,
            "medium_label": table_config.medium_label,
            "long_label": table_config.long_label,
            "description": table_config.description,
            "gene_columns": ",".join(data_and_meta.gene_columns),
            "gene_species": data_and_meta.gene_species,
            "display_columns": ",".join(data_and_meta.display_columns),
            "scalar_columns": ",".join(data_and_meta.scalar_columns),
            "link_tables": ",".join(
                link_table.get_meta_entry()
                for link_table in data_and_meta.link_tables
            ),
            "links": json.dumps(
                [link.to_json_dict() for link in table_config.links]
            )
            if table_config.links
            else None,
            "categories": ",".join(table_config.categories)
            if table_config.categories
            else None,
            "source": table_config.source,
            "assay": ",".join(table_config.assay) if table_config.assay else None,
            "condition": ",".join(table_config.condition)
            if table_config.condition
            else None,
            "field_labels": json.dumps(filtered_field_labels)
            if filtered_field_labels
            else None,
            "column_labels": json.dumps(filtered_column_labels)
            if filtered_column_labels
            else None,
            "organism": table_config.organism,
            "organism_key": ",".join(table_config.organism_key)
            if table_config.organism_key
            else None,
            "publication_first_author": table_config.publication_first_author,
            "publication_last_author": table_config.publication_last_author,
            "publication_author_count": table_config.publication_author_count,
            "publication_authors": json.dumps(table_config.publication_authors)
            if table_config.publication_authors
            else None,
            "publication_year": table_config.publication_year,
            "publication_journal": table_config.publication_journal,
            "publication_doi": table_config.publication_doi,
            "publication_pmid": table_config.publication_pmid,
            "publication_sspsygene_grants": json.dumps(
                table_config.publication_sspsygene_grants
            )
            if table_config.publication_sspsygene_grants
            else None,
            "pvalue_column": table_config.pvalue_column,
            "fdr_column": table_config.fdr_column,
            "effect_column": table_config.effect_column,
            "include_in_meta_analysis": 1 if table_config.meta_analysis else 0,
            "why_excluded_from_meta_analysis": table_config.why_excluded_from_meta_analysis,
            "include_in_overview_matrix": 1 if table_config.overview_matrix else 0,
            "expand_in_overview_matrix": 1
            if table_config.overview_matrix_expand
            else 0,
            "preprocessing": json.dumps(preprocessing_dict)
            if preprocessing_dict
            else None,
        }
        columns = ", ".join(row.keys())
        placeholders = ", ".join(f":{col}" for col in row.keys())
        cur.execute(
            f"INSERT INTO data_tables ({columns}) VALUES ({placeholders})",
            row,
        )
    # Create changelog_entries table
    cur.execute(
        """CREATE TABLE changelog_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT,
        date TEXT,
        message TEXT)"""
    )
    for table_config in table_configs:
        if table_config.table in set(skipped):
            continue
        for entry in table_config.changelog:
            cur.execute(
                "INSERT INTO changelog_entries (table_name, date, message) VALUES (?, ?, ?)",
                (table_config.table, entry.get("date"), entry.get("message")),
            )

    create_indexes(
        conn,
        "data_tables",
        ["table_name", "gene_species", "link_tables"],
        skip=no_index,
    )
    create_indexes(
        conn,
        "changelog_entries",
        ["table_name", "date"],
        skip=no_index,
    )
    conn.commit()

    # Print summary
    all_tables = loaded + skipped
    if all_tables:
        name_width = max(len(t) for t in all_tables)
        header_table = "Table"
        header_status = "Status"
        name_width = max(name_width, len(header_table))
        status_width = max(len(header_status), len("Skipped (missing)"))
        divider = f"+-{'-' * name_width}-+-{'-' * status_width}-+"
        click.echo("")
        click.echo(divider)
        click.echo(
            f"| {header_table:<{name_width}} | {header_status:<{status_width}} |"
        )
        click.echo(divider)
        skipped_set = set(skipped)
        for table in all_tables:
            if table in skipped_set:
                status = click.style("Skipped (missing)", fg="yellow", bold=True)
                # Pad manually since style adds invisible escape chars
                pad = status_width - len("Skipped (missing)")
            else:
                status = click.style("Loaded", fg="green", bold=True)
                pad = status_width - len("Loaded")
            click.echo(f"| {table:<{name_width}} | {status}{' ' * pad} |")
        click.echo(divider)
        click.echo(
            f"  {click.style(str(len(loaded)), bold=True)} loaded, "
            f"{click.style(str(len(skipped)), bold=True)} skipped"
        )


def load_assay_types(conn: sqlite3.Connection, assay_types: dict[str, str]) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE assay_types (
        key TEXT PRIMARY KEY,
        label TEXT)"""
    )
    for key, label in assay_types.items():
        cur.execute(
            "INSERT INTO assay_types (key, label) VALUES (?, ?)",
            (key, label),
        )
    conn.commit()


def load_condition_types(conn: sqlite3.Connection, condition_types: dict[str, str]) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE condition_types (
        key TEXT PRIMARY KEY,
        label TEXT)"""
    )
    for key, label in condition_types.items():
        cur.execute(
            "INSERT INTO condition_types (key, label) VALUES (?, ?)",
            (key, label),
        )
    conn.commit()


def load_organism_types(
    conn: sqlite3.Connection, organism_types: dict[str, str]
) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE organism_types (
        key TEXT PRIMARY KEY,
        label TEXT)"""
    )
    for key, label in organism_types.items():
        cur.execute(
            "INSERT INTO organism_types (key, label) VALUES (?, ?)",
            (key, label),
        )
    conn.commit()


def load_modalities(
    conn: sqlite3.Connection, modalities: list[dict[str, Any]]
) -> None:
    """Write the modality taxonomy for the overview matrix (#211).

    Modalities are the user-facing columns of the perturbed-gene × modality
    overview table (epic #220). Unlike the flat assay/condition/organism label
    maps, each modality carries a list of assay-type keys it maps to plus an
    `always_show` flag, so the table stores that richer shape. `sort_order`
    preserves the display order from globals.yaml (the list index)."""
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE modalities (
        key TEXT PRIMARY KEY,
        label TEXT,
        assay_types TEXT,
        always_show INTEGER NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL)"""
    )
    for sort_order, entry in enumerate(modalities):
        cur.execute(
            "INSERT INTO modalities "
            "(key, label, assay_types, always_show, sort_order) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                entry["key"],
                entry["label"],
                json.dumps(entry.get("assayTypes", [])),
                int(entry.get("alwaysShow", False)),
                sort_order,
            ),
        )
    conn.commit()


def load_llm_search_results(
    conn: sqlite3.Connection,
    data_dir: Path,
    *,
    no_index: bool = False,
) -> None:
    """Load LLM-generated search results from per-gene JSON files into SQLite."""
    results_dir = data_dir / "llm_gene_results"
    if not results_dir.exists():
        click.echo("\n  No LLM gene results directory found, skipping.")
        return

    gene_files = sorted(results_dir.glob("*.json"))
    if not gene_files:
        click.echo("\n  No LLM gene result files found, skipping.")
        return

    click.echo("\nLoading LLM search results...")

    conn.execute(
        """CREATE TABLE llm_gene_results (
        central_gene_id INTEGER PRIMARY KEY,
        pubmed_links TEXT,
        summary TEXT,
        status TEXT,
        search_date TEXT
        )"""
    )

    count = 0
    for gene_file in gene_files:
        with open(gene_file, "r") as f:
            info = json.load(f)
        conn.execute(
            "INSERT INTO llm_gene_results "
            "(central_gene_id, pubmed_links, summary, status, search_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                info["central_gene_id"],
                info.get("pubmed_links"),
                info.get("summary"),
                info.get("status", "results"),
                info.get("search_date", "unknown"),
            ),
        )
        count += 1

    if not no_index:
        conn.execute(
            "CREATE INDEX llm_gene_results_idx ON llm_gene_results (central_gene_id)"
        )
    conn.commit()
    click.echo(
        f"  Loaded LLM results for {click.style(str(count), bold=True)} genes "
        f"from {click.style(str(len(gene_files)), bold=True)} files"
    )


def load_db(
    db_name: Path,
    table_configs: list[TableToProcessConfig],
    assay_types: dict[str, str] | None = None,
    condition_types: dict[str, str] | None = None,
    organism_types: dict[str, str] | None = None,
    modalities: list[dict[str, Any]] | None = None,
    column_header_tokens: dict[str, str] | None = None,
    skip_missing: bool = False,
    no_index: bool = False,
    data_dir: Path | None = None,
    skip_gene_descriptions: bool = False,
    test_central_gene_ids: set[int] | None = None,
) -> None:
    """Build the dataset SQLite DB (sspsygene.db) and atomically swap it in.

    As of issue #176 this does NOT compute the combined-p-value meta-analysis,
    and as of the #222 follow-up it does NOT materialize the overview matrix
    either. Both are separate, independent-cadence steps that read this DB and
    write their own files (`sspsygene meta-analysis` → sspsygene-meta.db;
    `sspsygene overview-matrix` → sspsygene-overview.db)."""
    logger = logging.getLogger(__name__)
    db_name.parent.mkdir(parents=True, exist_ok=True)

    # Build a fresh DB at `{db_name}.new` and atomically swap it into place.
    # This lets long-running readers (the web process) keep serving the old
    # inode while we build, then flip to the new one on the next stat check
    # without ever observing a missing or half-written file.
    staging = _staging_path(db_name)

    with NewSqlite3(staging, logger) as new_sqlite3:
        conn = new_sqlite3.conn
        load_data_tables(
            conn,
            table_configs,
            skip_missing=skip_missing,
            no_index=no_index,
            test_central_gene_ids=test_central_gene_ids,
            column_header_tokens=column_header_tokens,
        )
        load_gene_tables(conn, no_index=no_index)
        compute_ensembl_to_symbol(conn, no_index=no_index)
        load_assay_types(conn, assay_types or {})
        load_condition_types(conn, condition_types or {})
        load_organism_types(conn, organism_types or {})
        load_modalities(conn, modalities or [])
        # The overview matrix (#222) is derived purely from the tables built
        # above, but it is materialized into its own file by `sspsygene
        # overview-matrix` (see run_overview_matrix) rather than inline here, so
        # the main dataset DB stays lean and the matrix rebuilds on its own
        # cadence — the same separation as the meta-analysis (#176).
        if data_dir and not skip_gene_descriptions:
            copy_gene_descriptions(conn, data_dir, no_index=no_index)
        if data_dir:
            load_llm_search_results(conn, data_dir, no_index=no_index)

    # Build the user-facing download artifacts as BLOBs in the staging DB
    # (per-table TSVs, metadata YAMLs, preprocessing YAMLs, manifest, README,
    # all-tables.zip). They land in the `export_files` table and are served
    # by /api/download — there is no exports/ directory on the filesystem.
    # Done BEFORE the atomic swap so the swapped-in DB has both data tables
    # and exports in one consistent observation.
    try:
        write_exports(staging)
    except Exception:
        logger.exception(
            "write_exports failed — DB will be swapped without download bundles"
        )

    _checkpoint_and_swap(staging, db_name)


def _staging_path(db_name: Path) -> Path:
    """`{db}.new` staging sibling, with any stale WAL/SHM sidecars removed."""
    staging = db_name.with_name(db_name.name + ".new")
    for p in (
        staging,
        staging.with_name(staging.name + "-wal"),
        staging.with_name(staging.name + "-shm"),
    ):
        p.unlink(missing_ok=True)
    return staging


def _checkpoint_and_swap(staging: Path, db_name: Path) -> None:
    """Checkpoint the staging DB to a self-contained file and atomically swap
    it onto `db_name`. Shared by the dataset build (`load_db`) and the
    meta-analysis build (`run_meta_analysis`)."""
    # Checkpoint WAL into the main file and switch to rollback journal mode so
    # the final file is self-contained — no -wal/-shm sidecars needed by readers.
    with sqlite3.connect(staging) as swap_conn:
        swap_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        swap_conn.execute("PRAGMA journal_mode=DELETE")
    for leftover in (
        staging.with_name(staging.name + "-wal"),
        staging.with_name(staging.name + "-shm"),
    ):
        leftover.unlink(missing_ok=True)

    # Make the final DB group-writable (0664) BEFORE the swap so the mode bits
    # travel with the inode through the atomic rename. Without this, sqlite
    # creates the staging file under the process umask (0644 on a umask-022
    # host), and every rebuild would silently replace a group-writable DB with
    # a group-read-only one — breaking overwrites for other members of the
    # `protein` group on the shared psygene/hgwdev checkouts. os.chmod is
    # deterministic regardless of umask (mirrors combined_pvalues/r_cache.py).
    os.chmod(staging, 0o664)

    # Atomically replace the live DB. POSIX rename is atomic on the same
    # filesystem, which the data/db directory always is.
    staging.replace(db_name)

    # Old reader FDs still point at the now-unlinked inode of the previous
    # DB; remove any leftover WAL/SHM sidecars for that inode so they don't
    # confuse fresh openers.
    for old_sidecar in (
        db_name.with_name(db_name.name + "-wal"),
        db_name.with_name(db_name.name + "-shm"),
    ):
        old_sidecar.unlink(missing_ok=True)


# Schema version of the meta DB layout. Bump if the combined_pvalue_groups /
# per-group table shape changes in a way the web app must notice.
META_SCHEMA_VERSION = "1"


def _write_meta_analysis_info(
    conn: sqlite3.Connection,
    main_db: Path,
    deg_assays: set[str] | None,
) -> None:
    """Record provenance + a fingerprint of the source dataset DB into the meta
    DB, so the web app can detect when the meta-analysis has drifted from the
    underlying datasets and show a stale-meta banner (issue #176).

    The fingerprint is the source DB's (mtime, size) at meta-build time. The
    dataset build's atomic swap mints a fresh inode + mtime on every `load-db`,
    so any dataset rebuild bumps the fingerprint and marks the meta as stale
    until `meta-analysis` is re-run. This is an advisory signal, not a hard
    consistency guarantee — the banner never blocks rendering."""
    st = main_db.stat()
    built_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    info: dict[str, str] = {
        "schema_version": META_SCHEMA_VERSION,
        "built_at": built_at,
        "source_db_mtime": repr(st.st_mtime),
        "source_db_size": str(st.st_size),
        "meta_assays": ",".join(sorted(deg_assays)) if deg_assays else "",
    }
    conn.execute(
        "CREATE TABLE meta_analysis_info (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.executemany(
        "INSERT INTO meta_analysis_info (key, value) VALUES (?, ?)",
        list(info.items()),
    )
    conn.commit()


def run_meta_analysis(
    main_db: Path,
    meta_db: Path,
    *,
    hgnc_path: Path | None = None,
    no_index: bool = False,
    nimh_csv_path: Path | None = None,
    tf_list_path: Path | None = None,
    use_r_cache: bool = True,
    deg_assays: set[str] | None = None,
) -> None:
    """Compute the combined-p-value meta-analysis into a standalone meta DB.

    Reads the already-built dataset DB at `main_db` (ATTACHed read-only as
    `src`), computes the combined p-values restricted to `deg_assays`, and
    atomically swaps the result onto `meta_db`. Never touches `main_db`.

    The dataset DB must already exist — this is the second of the two
    independent command chains in issue #176 (`load-db` then `meta-analysis`)."""
    logger = logging.getLogger(__name__)
    if not main_db.exists():
        raise ValueError(
            f"Dataset DB not found at {main_db}; run `sspsygene load-db` first."
        )
    meta_db.parent.mkdir(parents=True, exist_ok=True)
    staging = _staging_path(meta_db)

    with NewSqlite3(staging, logger) as new_sqlite3:
        conn = new_sqlite3.conn
        # ATTACH the dataset DB read-only so the meta build can read its tables
        # without ever locking or mutating the file the web app serves. URI
        # attach is honored because NewSqlite3 opens the connection with uri=True.
        conn.execute(f"ATTACH DATABASE 'file:{main_db}?mode=ro' AS src")
        compute_combined_pvalues(
            conn,
            hgnc_path=hgnc_path,
            no_index=no_index,
            nimh_csv_path=nimh_csv_path,
            tf_list_path=tf_list_path,
            use_r_cache=use_r_cache,
            src_schema="src",
            deg_assays=deg_assays,
        )
        _write_meta_analysis_info(conn, main_db, deg_assays)
        # Detach before the context manager's PRAGMA optimize / commit so those
        # never reach across into the read-only source DB.
        conn.execute("DETACH DATABASE src")

    _checkpoint_and_swap(staging, meta_db)
    click.echo(
        click.style(
            f"Wrote meta-analysis to {meta_db}", fg="green", bold=True
        )
    )


def run_overview_matrix(
    main_db: Path,
    overview_db: Path,
    *,
    no_index: bool = False,
    min_groups: int = 1,
) -> None:
    """Materialize the collated overview matrix into a standalone DB (#222).

    Reads the already-built dataset DB at `main_db` (ATTACHed read-only as
    `src`), materializes the `overview_matrix_*` tables, and atomically swaps
    the result onto `overview_db`. Never touches `main_db`.

    This is the overview-matrix analogue of `run_meta_analysis`: a second,
    independent-cadence build over the dataset DB (`load-db` then
    `overview-matrix`), so the main DB stays lean and the web app reads the
    matrix from its own ATTACHed file."""
    logger = logging.getLogger(__name__)
    if not main_db.exists():
        raise ValueError(
            f"Dataset DB not found at {main_db}; run `sspsygene load-db` first."
        )
    overview_db.parent.mkdir(parents=True, exist_ok=True)
    staging = _staging_path(overview_db)

    with NewSqlite3(staging, logger) as new_sqlite3:
        conn = new_sqlite3.conn
        # ATTACH the dataset DB read-only so the build reads its tables without
        # ever locking or mutating the file the web app serves. URI attach is
        # honored because NewSqlite3 opens the connection with uri=True.
        conn.execute(f"ATTACH DATABASE 'file:{main_db}?mode=ro' AS src")
        materialize_overview_matrix(
            conn, no_index=no_index, min_groups=min_groups, src_schema="src"
        )
        # Detach before the context manager's PRAGMA optimize / commit so those
        # never reach across into the read-only source DB.
        conn.execute("DETACH DATABASE src")

    _checkpoint_and_swap(staging, overview_db)
    click.echo(
        click.style(
            f"Wrote overview matrix to {overview_db}", fg="green", bold=True
        )
    )
