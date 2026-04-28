import json
import logging
from pathlib import Path
import sqlite3
import sys

import click

from processing.central_gene_table import get_central_gene_table
from processing.combined_pvalues import compute_combined_pvalues
from processing.effect_distributions import compute_effect_distributions
from processing.gene_descriptions import copy_gene_descriptions
from processing.new_sqlite3 import NewSqlite3
from processing.sql_utils import sanitize_identifier
from processing.types.table_to_process_config import TableToProcessConfig


def create_indexes(
    conn: sqlite3.Connection, table: str, idx_fields: list[str], *, skip: bool = False
) -> None:
    if skip:
        return
    table = sanitize_identifier(table)
    for field in idx_fields:
        field = sanitize_identifier(field)
        print(f"Creating index for {field}")
        sql = f"CREATE INDEX {table}_{field}_idx ON {table} ({field})"
        conn.execute(sql)


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
    for field in _NOCASE_INDEXES.get(table, []):
        field = sanitize_identifier(field)
        idx_name = f"{table}_{field}_nocase_idx"
        print(f"Creating NOCASE index {idx_name}")
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
        manually_added BOOLEAN
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
        )
        cur.execute(
            """INSERT INTO central_gene (
            id, human_symbol, human_entrez_gene, hgnc_id, mouse_symbols, 
            mouse_mgi_accession_ids, mouse_ensembl_genes, human_synonyms, mouse_synonyms, dataset_names, num_datasets, manually_added) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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


def load_data_tables(
    conn: sqlite3.Connection,
    table_configs: list[TableToProcessConfig],
    skip_missing: bool = False,
    *,
    no_index: bool = False,
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
        disease TEXT,
        field_labels TEXT,
        organism TEXT,
        publication_first_author TEXT,
        publication_last_author TEXT,
        publication_author_count INTEGER,
        publication_authors TEXT,
        publication_year INTEGER,
        publication_journal TEXT,
        publication_doi TEXT,
        publication_pmid TEXT,
        pvalue_column TEXT,
        fdr_column TEXT,
        effect_column TEXT)"""
    )
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
        data_and_meta = table_config.load_data_table()
        loaded.append(table_config.table)
        data_and_meta.data.to_sql(
            table_config.table, conn, if_exists="replace", index=False
        )
        for link_table in data_and_meta.link_tables:
            link_table.write_to_sqlite(conn)
            create_indexes(
                conn, link_table.link_table_name, ["central_gene_id"], skip=no_index
            )
        assert "id" in data_and_meta.data.columns, "id column not found in data"
        create_indexes(conn, table_config.table, ["id"], skip=no_index)

        # Only store field labels for columns that actually exist in the table
        display_col_set = set(data_and_meta.display_columns)
        filtered_field_labels = {
            k: v for k, v in table_config.field_labels.items() if k in display_col_set
        }

        cur.execute(
            """INSERT INTO data_tables (
            table_name, short_label, medium_label, long_label, description, gene_columns,
            gene_species, display_columns,
            scalar_columns, link_tables,
            links, categories, source, assay, disease, field_labels, organism,
            publication_first_author, publication_last_author, publication_author_count, publication_authors, publication_year,
            publication_journal, publication_doi, publication_pmid,
            pvalue_column, fdr_column, effect_column)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                table_config.table,
                table_config.short_label,
                table_config.medium_label,
                table_config.long_label,
                table_config.description,
                ",".join(data_and_meta.gene_columns),
                data_and_meta.gene_species,
                ",".join(data_and_meta.display_columns),
                ",".join(data_and_meta.scalar_columns),
                ",".join(
                    link_table.get_meta_entry()
                    for link_table in data_and_meta.link_tables
                ),
                ",".join(table_config.links) if table_config.links else None,
                ",".join(table_config.categories) if table_config.categories else None,
                table_config.source,
                ",".join(table_config.assay) if table_config.assay else None,
                ",".join(table_config.disease) if table_config.disease else None,
                json.dumps(filtered_field_labels) if filtered_field_labels else None,
                table_config.organism,
                table_config.publication_first_author,
                table_config.publication_last_author,
                table_config.publication_author_count,
                json.dumps(table_config.publication_authors)
                if table_config.publication_authors
                else None,
                table_config.publication_year,
                table_config.publication_journal,
                table_config.publication_doi,
                table_config.publication_pmid,
                table_config.pvalue_column,
                table_config.fdr_column,
                table_config.effect_column,
            ),
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


def load_disease_types(conn: sqlite3.Connection, disease_types: dict[str, str]) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE disease_types (
        key TEXT PRIMARY KEY,
        label TEXT)"""
    )
    for key, label in disease_types.items():
        cur.execute(
            "INSERT INTO disease_types (key, label) VALUES (?, ?)",
            (key, label),
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
    disease_types: dict[str, str] | None = None,
    skip_missing: bool = False,
    hgnc_path: Path | None = None,
    no_index: bool = False,
    data_dir: Path | None = None,
    skip_gene_descriptions: bool = False,
    nimh_csv_path: Path | None = None,
    tf_list_path: Path | None = None,
    skip_meta_analysis: bool = False,
) -> None:
    logger = logging.getLogger(__name__)
    db_name.parent.mkdir(parents=True, exist_ok=True)

    # Build a fresh DB at `{db_name}.new` and atomically swap it into place.
    # This lets long-running readers (the web process) keep serving the old
    # inode while we build, then flip to the new one on the next stat check
    # without ever observing a missing or half-written file.
    staging = db_name.with_name(db_name.name + ".new")
    for p in (
        staging,
        staging.with_name(staging.name + "-wal"),
        staging.with_name(staging.name + "-shm"),
    ):
        p.unlink(missing_ok=True)

    with NewSqlite3(staging, logger) as new_sqlite3:
        conn = new_sqlite3.conn
        load_data_tables(
            conn, table_configs, skip_missing=skip_missing, no_index=no_index
        )
        load_gene_tables(conn, no_index=no_index)
        load_assay_types(conn, assay_types or {})
        load_disease_types(conn, disease_types or {})
        if data_dir and not skip_gene_descriptions:
            copy_gene_descriptions(conn, data_dir, no_index=no_index)
        if not skip_meta_analysis:
            compute_combined_pvalues(
                conn,
                hgnc_path=hgnc_path,
                no_index=no_index,
                nimh_csv_path=nimh_csv_path,
                tf_list_path=tf_list_path,
            )
        compute_effect_distributions(conn, no_index=no_index)
        if data_dir:
            load_llm_search_results(conn, data_dir, no_index=no_index)

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
