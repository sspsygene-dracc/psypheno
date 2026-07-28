"""Derive a destination DB (int / prod) from the dev superset (#225).

The dataset DB is built once, on dev, containing every dataset. A promotion to
int or prod runs this subsetter over that file to produce a DB containing only
the datasets whose `deployTo` names that destination.

**Fail-closed.** The subset is created as a fresh, empty SQLite file into which
only explicitly allow-listed content is copied. It never starts from a byte
copy of the superset and deletes:

- `cp` + `DELETE` is fail-open. Prod's file would begin as a byte-for-byte copy
  of the embargoed superset, and anything added later — a new metadata table, a
  new kind of `export_files` path — would ship to prod until someone remembered
  to extend the deletion list.
- Without a completed `VACUUM` the freed pages still *physically contain* the
  deleted rows, in a file we serve for download.

The same reasoning drives `_classify_source_tables`: every table in the source
must be explicitly classified. A table this module has never heard of is an
error, not a silent copy and not a silent drop — adding a table to the build
forces a decision about what it means for a destination.

What it does NOT do: re-read a raw data file, re-run gene resolution, or
re-parse HGNC/MGI/Alliance. That expensive single-threaded work happens once,
in the dev build; everything here is derivable from the superset because
`central_gene_usage` (#225) preserves the (gene, table, name) pairing that
central_gene's flattened columns throw away.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from processing.build_info import copy_build_info
from processing.exports import write_exports
from processing.instances import INSTANCE_ORDER
from processing.new_sqlite3 import NewSqlite3
from processing.sql_utils import sanitize_identifier

logger = logging.getLogger(__name__)


# Global taxonomy + build identity: destination-independent, copied verbatim.
_GLOBAL_TABLES = (
    "assay_types",
    "condition_types",
    "organism_types",
    "modalities",
)

# Scoped to member tables via a `table_name` column.
_MEMBER_SCOPED_TABLES = (
    "data_tables",
    "dataset_destinations",
    "changelog_entries",
    "central_gene_usage",
)

# Scoped to surviving genes via a `central_gene_id` column. Everything these
# hold is a property of the gene rather than of a dataset, so a surviving gene
# keeps its rows unchanged.
_GENE_SCOPED_TABLES = (
    "extra_mouse_symbols",
    "ensembl_to_symbol",
    "gene_descriptions",
    "llm_gene_results",
)

# Tables `load-db` only creates when their optional inputs are present
# (--skip-gene-descriptions, no llm_gene_results directory). A source without
# them is a normal build, not a broken one, so they are skipped rather than
# treated as a missing-table error. Every *other* table is required: refusing
# to subset a source that is missing one is the fail-closed choice.
_OPTIONAL_TABLES = frozenset({"gene_descriptions", "llm_gene_results"})

# Rebuilt rather than filtered, because their contents are aggregates over the
# set of tables that used each gene.
_RECOMPUTED_TABLES = ("central_gene", "extra_gene_synonyms")

# Regenerated from the subset's own data_tables by write_exports.
_REGENERATED_TABLES = ("export_files",)

# SQLite's own bookkeeping. Recreated implicitly by AUTOINCREMENT columns and
# by PRAGMA optimize; copying them would be meaningless or actively wrong.
_INTERNAL_TABLES = ("sqlite_sequence", "sqlite_stat1")

# Build identity — same build as the superset, so the meta / overview DBs
# promoted alongside this file still match it.
_BUILD_INFO_TABLE = "build_info"


class SubsetError(RuntimeError):
    """The subset could not be produced. Never leaves a partial file in place."""


def _source_has(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM src.sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def _table_sql(conn: sqlite3.Connection, schema: str, name: str) -> str:
    row = conn.execute(
        f"SELECT sql FROM {schema}.sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    if not row or not row[0]:
        raise SubsetError(f"source DB has no table {name!r}")
    return str(row[0])


def _copy_schema(conn: sqlite3.Connection, name: str) -> None:
    """Recreate `name` in the destination with the source's exact DDL.

    Copying the DDL rather than restating it keeps dynamically-shaped tables
    (the per-dataset data tables and their link tables) correct, and keeps the
    fixed ones from drifting away from sq_load's definitions.
    """
    conn.execute(_table_sql(conn, "src", name))


def _copy_indexes(conn: sqlite3.Connection, name: str) -> None:
    """Recreate `name`'s indexes from the source's DDL.

    This is how the subset ends up with exactly the indexes `load_gene_tables`
    / `load_data_tables` created — including the NOCASE ones autocomplete
    depends on — without a second copy of that list to keep in sync.
    """
    rows = conn.execute(
        "SELECT sql FROM src.sqlite_master WHERE type='index' AND tbl_name=? "
        "AND sql IS NOT NULL",
        (name,),
    ).fetchall()
    for (sql,) in rows:
        conn.execute(sql)


def _classify_source_tables(
    conn: sqlite3.Connection, member_tables: set[str], all_tables: set[str]
) -> tuple[list[str], list[str]]:
    """Split the source's tables into (member data tables, member link tables),
    erroring on anything unrecognized.

    The error is the fail-closed guarantee: a table added to the build after
    this module was written stops the promotion until someone classifies it,
    rather than being copied to prod by accident or dropped from prod silently.
    """
    known = {
        *_GLOBAL_TABLES,
        *_MEMBER_SCOPED_TABLES,
        *_GENE_SCOPED_TABLES,
        *_RECOMPUTED_TABLES,
        *_REGENERATED_TABLES,
        *_INTERNAL_TABLES,
        _BUILD_INFO_TABLE,
    }

    # Link tables are named "{parent_data_table}__{link_name}" and are declared
    # in data_tables.link_tables; derive them from the declaration rather than
    # from the name, so an odd table name can't masquerade as a link table.
    link_by_parent: dict[str, list[str]] = {}
    for parent, raw in conn.execute(
        "SELECT table_name, link_tables FROM src.data_tables"
    ):
        names: list[str] = []
        for entry in (raw or "").split(","):
            parts = entry.strip().split(":")
            if len(parts) >= 3:
                names.append(sanitize_identifier(parts[1]))
        link_by_parent[parent] = names

    declared_links = {n for names in link_by_parent.values() for n in names}

    present = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM src.sqlite_master WHERE type='table'"
        )
    }
    unknown = present - known - all_tables - declared_links
    if unknown:
        raise SubsetError(
            f"source DB contains table(s) this subsetter does not know how to "
            f"classify: {sorted(unknown)}. Refusing to subset rather than "
            f"guess whether they may be promoted. Classify them in "
            f"processing/subset_db.py (see the module docstring) and re-run."
        )

    member_data = sorted(t for t in member_tables if t in present)
    member_links = sorted(
        name
        for parent in member_tables
        for name in link_by_parent.get(parent, [])
        if name in present
    )
    return member_data, member_links


def _member_tables(conn: sqlite3.Connection, destination: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM src.dataset_destinations WHERE destination = ?",
            (destination,),
        )
    }


def _rebuild_gene_tables(conn: sqlite3.Connection) -> int:
    """Rebuild central_gene / extra_gene_synonyms scoped to the member tables.

    Reads the member set from the destination's own `dataset_destinations`,
    which by this point holds exactly the member tables.

    Only three things about a gene are destination-dependent, and all are
    derivable from central_gene_usage restricted to the member tables:

    - whether the gene survives at all (it must have at least one member usage;
      `load_gene_tables` skips entries with `used` false);
    - `dataset_names` / `num_datasets`, which are that gene's distinct member
      table names;
    - the `human_synonyms` / `mouse_synonyms` columns and the *human*
      extra_gene_synonyms rows, which sq_load stores as
      `entry.<species>_synonyms & used_<species>_names`. Member usages are a
      subset of all usages, so re-intersecting the stored value with the member
      matched names is exactly the from-scratch result.

    Everything else — mouse_symbols, MGI/Ensembl ids, hgnc_id, entrez, kind,
    manually_added, and the *mouse* extra_gene_synonyms rows (sq_load inserts
    those unintersected, from MGI rather than from usage) — is a property of
    the gene, not of the datasets, and is copied verbatim.
    """
    conn.execute(
        "CREATE TEMP TABLE member_usage AS "
        "SELECT central_gene_id, table_name, species, matched_name "
        "FROM src.central_gene_usage WHERE table_name IN "
        "(SELECT table_name FROM dataset_destinations)"
    )
    conn.execute(
        "CREATE INDEX member_usage_gene_idx ON member_usage (central_gene_id)"
    )

    surviving = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT central_gene_id FROM member_usage"
        )
    ]

    # dataset_names / num_datasets, and the per-species matched-name sets used
    # to re-intersect the synonym columns.
    names_by_gene: dict[int, set[str]] = {}
    matched_by_gene: dict[int, dict[str, set[str]]] = {}
    for gene_id, table_name, species, matched_name in conn.execute(
        "SELECT central_gene_id, table_name, species, matched_name FROM member_usage"
    ):
        names_by_gene.setdefault(gene_id, set()).add(table_name)
        matched_by_gene.setdefault(gene_id, {}).setdefault(species, set()).add(
            matched_name
        )

    columns = [
        row[1] for row in conn.execute("PRAGMA src.table_info(central_gene)")
    ]
    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join("?" for _ in columns)

    rows_out = []
    for row in conn.execute(
        f"SELECT {col_list} FROM src.central_gene WHERE id IN "
        f"(SELECT central_gene_id FROM member_usage)"
    ):
        values = dict(zip(columns, row))
        gene_id = values["id"]
        member_names = sorted(names_by_gene.get(gene_id, set()))
        values["dataset_names"] = ",".join(member_names) or None
        values["num_datasets"] = len(member_names)
        matched = matched_by_gene.get(gene_id, {})
        for species, column in (("human", "human_synonyms"), ("mouse", "mouse_synonyms")):
            stored = values.get(column)
            if stored is None:
                continue
            kept = sorted(
                s for s in stored.split(",") if s and s in matched.get(species, set())
            )
            values[column] = ",".join(kept)
        rows_out.append(tuple(values[c] for c in columns))

    conn.executemany(
        f"INSERT INTO central_gene ({col_list}) VALUES ({placeholders})", rows_out
    )

    # Human synonym rows are the intersected set, so they filter by member
    # matched name. Mouse rows are unintersected in the source and therefore
    # destination-independent for a surviving gene.
    conn.execute(
        "INSERT INTO extra_gene_synonyms (id, central_gene_id, species, synonym) "
        "SELECT s.id, s.central_gene_id, s.species, s.synonym "
        "FROM src.extra_gene_synonyms s "
        "WHERE s.central_gene_id IN (SELECT central_gene_id FROM member_usage) "
        "  AND (s.species <> 'h' OR EXISTS ("
        "        SELECT 1 FROM member_usage u "
        "         WHERE u.central_gene_id = s.central_gene_id "
        "           AND u.species = 'human' AND u.matched_name = s.synonym))"
    )
    return len(surviving)


def subset_db(
    source: Path,
    destination_db: Path,
    destination: str,
    *,
    verify: bool = True,
    config_root: Path | None = None,
) -> None:
    """Write the `destination` subset of `source` to `destination_db`.

    The result is verified (unless `verify=False`) *before* it is swapped into
    place, so a bad subset never becomes a file anyone can promote.
    """
    if destination not in INSTANCE_ORDER:
        raise SubsetError(
            f"unknown destination {destination!r}; expected one of "
            f"{', '.join(INSTANCE_ORDER)}"
        )
    if not source.exists():
        raise SubsetError(f"source DB not found at {source}")
    if source.resolve() == destination_db.resolve():
        raise SubsetError(
            f"refusing to subset {source} onto itself — the destination must "
            f"be a different file"
        )

    destination_db.parent.mkdir(parents=True, exist_ok=True)
    staging = destination_db.with_name(destination_db.name + ".new")
    for leftover in (
        staging,
        staging.with_name(staging.name + "-wal"),
        staging.with_name(staging.name + "-shm"),
    ):
        leftover.unlink(missing_ok=True)

    with NewSqlite3(staging, logger) as new_sqlite3:
        conn = new_sqlite3.conn
        conn.execute(f"ATTACH DATABASE 'file:{source}?mode=ro' AS src")

        member_tables = _member_tables(conn, destination)
        if not member_tables:
            raise SubsetError(
                f"no table in {source} is labelled for destination "
                f"{destination!r}. Refusing to build an empty DB — check the "
                f"`deployTo` lists in data/datasets/*/config.yaml."
            )
        all_data_tables = {
            row[0] for row in conn.execute("SELECT table_name FROM src.data_tables")
        }
        member_data, member_links = _classify_source_tables(
            conn, member_tables, all_data_tables
        )

        logger.info(
            "Subsetting %s -> %s for %s: %d of %d data tables, %d link tables",
            source,
            destination_db,
            destination,
            len(member_data),
            len(all_data_tables),
            len(member_links),
        )

        # Same build as the superset — see build_info's module docstring.
        copy_build_info(conn, "src")

        for name in _GLOBAL_TABLES:
            _copy_schema(conn, name)
            conn.execute(f"INSERT INTO {name} SELECT * FROM src.{name}")
            _copy_indexes(conn, name)

        # dataset_destinations must land before anything that filters on it.
        #
        # Rows are scoped by member *table*, not by destination: a member table
        # keeps its full deployTo list. Restricting to the requested
        # destination would make the table mean something different in a subset
        # than in the superset, and would make the guard's config cross-check
        # compare ['prod'] against ['dev','int','prod'] on every row. Nothing
        # leaks — these are only ever rows for tables the destination already
        # has.
        _copy_schema(conn, "dataset_destinations")
        conn.executemany(
            "INSERT INTO dataset_destinations (dataset, table_name, destination) "
            "SELECT dataset, table_name, destination FROM src.dataset_destinations "
            "WHERE table_name = ?",
            [(name,) for name in sorted(member_tables)],
        )
        _copy_indexes(conn, "dataset_destinations")

        for name in ("data_tables", "changelog_entries", "central_gene_usage"):
            _copy_schema(conn, name)
            conn.execute(
                f"INSERT INTO {name} SELECT * FROM src.{name} WHERE table_name IN "
                f"(SELECT table_name FROM dataset_destinations)"
            )
            _copy_indexes(conn, name)

        for name in member_data + member_links:
            safe = sanitize_identifier(name)
            _copy_schema(conn, safe)
            conn.execute(f'INSERT INTO "{safe}" SELECT * FROM src."{safe}"')
            _copy_indexes(conn, safe)

        for name in _RECOMPUTED_TABLES:
            _copy_schema(conn, name)
        surviving = _rebuild_gene_tables(conn)
        for name in _RECOMPUTED_TABLES:
            _copy_indexes(conn, name)

        for name in _GENE_SCOPED_TABLES:
            if name in _OPTIONAL_TABLES and not _source_has(conn, name):
                logger.info("  source has no %s — skipping (optional)", name)
                continue
            _copy_schema(conn, name)
            conn.execute(
                f"INSERT INTO {name} SELECT * FROM src.{name} "
                f"WHERE central_gene_id IN (SELECT id FROM central_gene)"
            )
            _copy_indexes(conn, name)

        logger.info(
            "  %d of %d central_gene rows survive",
            surviving,
            conn.execute("SELECT count(*) FROM src.central_gene").fetchone()[0],
        )

        conn.execute("DROP TABLE IF EXISTS member_usage")
        # DETACH before the context manager's PRAGMA optimize, which must not
        # reach the read-only source.
        conn.commit()
        conn.execute("DETACH DATABASE src")

    # write_exports derives its table list from the file's own data_tables and
    # drops export_files first, so it needs no destination filtering at all —
    # a self-scoping property worth preserving whenever it is touched.
    write_exports(staging)

    if verify:
        # Import here: destination_guard imports nothing from this module, but
        # keeping the dependency lazy makes the two independently testable.
        from processing.destination_guard import verify_destination

        verify_destination(
            staging, destination, config_root=config_root, context="subset"
        )

    # Reuses load-db's swap so the chmod-0664-before-rename group-writable
    # invariant travels with the inode (see .claude/rules).
    from processing.sq_load import _checkpoint_and_swap

    _checkpoint_and_swap(staging, destination_db)
    logger.info("Subset written to %s", destination_db)
