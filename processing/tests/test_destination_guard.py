"""The destination guard must catch a planted leak in every place it scans (#225).

Each test plants one forbidden table name in one location and asserts the guard
finds it. The point is coverage of the *locations*: a leak that only shows up in
`central_gene.dataset_names` is just as much a disclosure as one that leaves a
whole table in the file, and a check that only looked at `data_tables` would
miss it.

The fixture is a hand-built miniature DB rather than the real loader's output,
so a test can plant exactly one thing and nothing else moves.
"""

from __future__ import annotations

import io
import sqlite3
import zipfile
from pathlib import Path

import pytest
import yaml

from processing.destination_guard import (
    DestinationGuardError,
    verify_destination,
)

MEMBER = "public_degs"
EMBARGOED = "secret_degs"


def _write_configs(root: Path) -> Path:
    """Two datasets: one prod-promotable, one dev-only."""
    for name, table, deploy_to in (
        ("public", MEMBER, ["dev", "prod"]),
        ("secret", EMBARGOED, ["dev"]),
    ):
        d = root / name
        d.mkdir(parents=True)
        (d / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "deployTo": deploy_to,
                    "tables": [{"table": table, "description": "d"}],
                }
            )
        )
    return root


def _make_db(path: Path, *, tables: list[str], labels: dict[str, list[str]]) -> None:
    """A minimal DB with the shape the guard scans."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE data_tables (table_name TEXT, dataset TEXT, link_tables TEXT);
        CREATE TABLE dataset_destinations (
            dataset TEXT, table_name TEXT, destination TEXT);
        CREATE TABLE changelog_entries (table_name TEXT, date TEXT, message TEXT);
        CREATE TABLE central_gene (id INTEGER PRIMARY KEY, dataset_names TEXT);
        CREATE TABLE central_gene_usage (
            central_gene_id INTEGER, table_name TEXT, species TEXT,
            matched_name TEXT);
        CREATE TABLE export_files (
            path TEXT PRIMARY KEY, content_type TEXT, content BLOB,
            size INTEGER, last_modified INTEGER);
        CREATE TABLE build_info (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    for table in tables:
        conn.execute(
            "INSERT INTO data_tables (table_name, dataset, link_tables) VALUES (?,?,?)",
            (table, table.split("_")[0], ""),
        )
        conn.execute(f'CREATE TABLE "{table}" (id INTEGER)')
        conn.execute(
            "INSERT INTO changelog_entries VALUES (?, '2026-01-01', 'note')",
            (table,),
        )
        conn.execute(
            "INSERT INTO central_gene_usage VALUES (1, ?, 'human', 'TCF4')",
            (table,),
        )
    for dataset, destinations in labels.items():
        table = MEMBER if dataset == "public" else EMBARGOED
        for destination in destinations:
            conn.execute(
                "INSERT INTO dataset_destinations VALUES (?, ?, ?)",
                (dataset, table, destination),
            )
    conn.execute(
        "INSERT INTO central_gene VALUES (1, ?)", (",".join(tables),)
    )
    conn.execute(
        "INSERT INTO build_info VALUES ('build_uuid', 'test-uuid')"
    )
    _write_zip(conn, [f"tables/{t}.tsv" for t in tables])
    conn.commit()
    conn.close()


def _write_zip(conn: sqlite3.Connection, members: list[str]) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for member in members:
            zf.writestr(member, "gene\tp\n")
    conn.execute("DELETE FROM export_files WHERE path = 'all-tables.zip'")
    conn.execute(
        "INSERT INTO export_files VALUES ('all-tables.zip', 'application/zip',"
        " ?, ?, 0)",
        (buf.getvalue(), len(buf.getvalue())),
    )


@pytest.fixture
def clean(tmp_path: Path) -> tuple[Path, Path]:
    """A prod DB that passes: only the prod-labelled table, everywhere."""
    config_root = _write_configs(tmp_path / "datasets")
    db = tmp_path / "prod.db"
    # Only the member dataset gets destination rows: subset-db scopes
    # dataset_destinations by member *table*, so a prod DB never carries a row
    # naming a dev-only dataset (and the guard flags it if one does).
    _make_db(db, tables=[MEMBER], labels={"public": ["dev", "prod"]})
    return db, config_root


def _expect_leak(db: Path, config_root: Path, needle: str) -> None:
    with pytest.raises(DestinationGuardError) as excinfo:
        verify_destination(db, "prod", config_root=config_root)
    message = str(excinfo.value)
    assert needle in message, message
    assert EMBARGOED in message
    # The banner is the operator's instruction; it must always be present.
    assert "PROMOTION ABORTED" in message
    assert "jbirgmei@gmail.com" in message


def test_clean_db_passes(clean: tuple[Path, Path]) -> None:
    db, config_root = clean
    verify_destination(db, "prod", config_root=config_root)


# ── one planted leak per scanned location ────────────────────────────────────


def test_catches_a_whole_table_left_in_the_file(clean: tuple[Path, Path]) -> None:
    db, config_root = clean
    conn = sqlite3.connect(db)
    conn.execute(f'CREATE TABLE "{EMBARGOED}" (id INTEGER)')
    conn.commit()
    conn.close()
    _expect_leak(db, config_root, "sqlite_master")


def test_catches_a_link_table_left_in_the_file(clean: tuple[Path, Path]) -> None:
    db, config_root = clean
    conn = sqlite3.connect(db)
    conn.execute(f'CREATE TABLE "{EMBARGOED}__gene" (central_gene_id INTEGER)')
    conn.commit()
    conn.close()
    _expect_leak(db, config_root, "link table")


def test_catches_a_data_tables_row(clean: tuple[Path, Path]) -> None:
    db, config_root = clean
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO data_tables (table_name, dataset, link_tables) "
        "VALUES (?, 'secret', '')",
        (EMBARGOED,),
    )
    conn.commit()
    conn.close()
    _expect_leak(db, config_root, "data_tables")


def test_catches_a_changelog_row(clean: tuple[Path, Path]) -> None:
    db, config_root = clean
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO changelog_entries VALUES (?, '2026-01-01', 'leaky note')",
        (EMBARGOED,),
    )
    conn.commit()
    conn.close()
    _expect_leak(db, config_root, "changelog_entries.table_name")


def test_catches_a_central_gene_dataset_names_mention(
    clean: tuple[Path, Path],
) -> None:
    """The comma-joined column is a real disclosure route: it names every table
    a gene appeared in, so a stale value leaks an embargoed dataset's name even
    when its rows are gone."""
    db, config_root = clean
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE central_gene SET dataset_names = ?", (f"{MEMBER},{EMBARGOED}",)
    )
    conn.commit()
    conn.close()
    _expect_leak(db, config_root, "central_gene.dataset_names")


def test_catches_a_central_gene_usage_row(clean: tuple[Path, Path]) -> None:
    db, config_root = clean
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO central_gene_usage VALUES (1, ?, 'human', 'TCF4')",
        (EMBARGOED,),
    )
    conn.commit()
    conn.close()
    _expect_leak(db, config_root, "central_gene_usage.table_name")


def test_catches_an_export_files_path(clean: tuple[Path, Path]) -> None:
    db, config_root = clean
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO export_files VALUES (?, 'text/tab-separated-values',"
        " X'00', 1, 0)",
        (f"tables/{EMBARGOED}.tsv",),
    )
    conn.commit()
    conn.close()
    _expect_leak(db, config_root, "export_files.path")


def test_catches_a_member_inside_all_tables_zip(clean: tuple[Path, Path]) -> None:
    """The zip is what a user actually downloads, so it is opened and its
    member list checked rather than trusted to follow from the blobs."""
    db, config_root = clean
    conn = sqlite3.connect(db)
    _write_zip(conn, [f"tables/{MEMBER}.tsv", f"tables/{EMBARGOED}.tsv"])
    conn.commit()
    conn.close()
    _expect_leak(db, config_root, "all-tables.zip")


# ── the independence property ────────────────────────────────────────────────


def test_catches_db_labels_disagreeing_with_the_configs(
    clean: tuple[Path, Path],
) -> None:
    """A DB built from a different revision of the configs than the checkout
    the operator is looking at. Nothing has leaked yet, but the labels can no
    longer be trusted, so the promotion stops."""
    db, config_root = clean
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE dataset_destinations SET destination = 'int' "
        "WHERE destination = 'prod'"
    )
    conn.commit()
    conn.close()
    with pytest.raises(DestinationGuardError, match="different configs"):
        verify_destination(db, "prod", config_root=config_root)


def test_catches_prod_labelled_data_missing_from_prod(
    clean: tuple[Path, Path],
) -> None:
    """Equality is asserted in both directions — the converse leak is a prod
    instance silently serving less than it should."""
    db, config_root = clean
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM data_tables WHERE table_name = ?", (MEMBER,))
    conn.commit()
    conn.close()
    with pytest.raises(DestinationGuardError, match="MISSING"):
        verify_destination(db, "prod", config_root=config_root)


def test_refuses_a_db_with_no_dataset_destinations(tmp_path: Path) -> None:
    """A pre-#225 DB cannot have its contents attributed to a destination, so
    it must not be promotable."""
    config_root = _write_configs(tmp_path / "datasets")
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE data_tables (table_name TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(DestinationGuardError, match="predates #225"):
        verify_destination(db, "prod", config_root=config_root)


def test_rejects_an_unknown_destination(clean: tuple[Path, Path]) -> None:
    db, config_root = clean
    with pytest.raises(DestinationGuardError, match="unknown destination"):
        verify_destination(db, "staging", config_root=config_root)


def test_config_without_deploy_to_is_an_error(clean: tuple[Path, Path]) -> None:
    """The guard's source of truth must actually declare destinations."""
    db, config_root = clean
    (config_root / "public" / "config.yaml").write_text(
        yaml.safe_dump({"tables": [{"table": MEMBER}]})
    )
    with pytest.raises(DestinationGuardError, match="malformed `deployTo`"):
        verify_destination(db, "prod", config_root=config_root)


# ── the derived DBs, under the destination-independent prod-only rule ────────


def _make_meta(path: Path, source_tables: str, source_uuid: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE combined_pvalue_groups (source_table_names TEXT);
        CREATE TABLE meta_analysis_info (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    conn.execute(
        "INSERT INTO combined_pvalue_groups VALUES (?)", (source_tables,)
    )
    conn.execute(
        "INSERT INTO meta_analysis_info VALUES ('source_build_uuid', ?)",
        (source_uuid,),
    )
    conn.commit()
    conn.close()


def test_catches_a_non_prod_table_in_the_meta_db(clean: tuple[Path, Path]) -> None:
    db, config_root = clean
    _make_meta(
        db.with_name("prod-meta.db"), f"{MEMBER},{EMBARGOED}", "test-uuid"
    )
    _expect_leak(db, config_root, "meta DB")


def test_meta_db_referencing_only_prod_tables_passes(
    clean: tuple[Path, Path],
) -> None:
    db, config_root = clean
    _make_meta(db.with_name("prod-meta.db"), MEMBER, "test-uuid")
    verify_destination(db, "prod", config_root=config_root)


def test_catches_a_meta_db_from_a_different_build(clean: tuple[Path, Path]) -> None:
    """Promotion copies main + meta + overview together. A meta DB carrying a
    different build UUID describes a different dataset set than the main DB it
    would be served beside."""
    db, config_root = clean
    _make_meta(db.with_name("prod-meta.db"), MEMBER, "some-other-build")
    with pytest.raises(DestinationGuardError, match="different dataset sets"):
        verify_destination(db, "prod", config_root=config_root)


def test_derived_check_can_be_skipped(clean: tuple[Path, Path]) -> None:
    db, config_root = clean
    _make_meta(db.with_name("prod-meta.db"), f"{MEMBER},{EMBARGOED}", "test-uuid")
    verify_destination(db, "prod", config_root=config_root, check_derived=False)
