"""The machine check standing between any DB and production (#225).

Answers one question: *does this file contain anything belonging to a dataset
that is not allowed on this destination?*

Two properties make it a real check rather than a restatement of the build:

1. **Independent source of truth.** The allowed set is re-read from the target
   checkout's `data/datasets/*/config.yaml`, and cross-checked against the DB's
   own `dataset_destinations`. A disagreement between the two is itself a
   failure — that is what catches a DB built from a different revision of the
   configs than the one the operator is looking at.

2. **Deny-scan, not allow-list.** For every table that must *not* be present it
   searches each place a table name can hide. Scanning for what must not be
   there means the check does not need updating every time a new table is added
   to the build — the new table's contents are still swept for forbidden names.

The equality assertion is deliberately two-directional: the DB's table set must
*equal* the labelled set, not merely be contained in it. That catches both "int
data leaked to prod" and the converse, "prod-labelled data silently missing
from prod".

The meta / overview rule is destination-independent: those DBs are computed
once from prod-labelled inputs and copied verbatim to every instance, so on
*any* instance they may reference prod-labelled tables only.

On failure this raises DestinationGuardError. Callers abort the whole
promotion, leave the target untouched, and exit non-zero. There is no --force.
"""

from __future__ import annotations

import io
import logging
import sqlite3
import zipfile
from pathlib import Path

import yaml

from processing.build_info import read_build_uuid
from processing.instances import INSTANCE_ORDER

logger = logging.getLogger(__name__)

_ABORT_BANNER = (
    "PROMOTION ABORTED — possible embargoed-data leak. Do not retry. "
    "Email jbirgmei@gmail.com with this full error message."
)

# The prod-only rule for derived DBs (see module docstring).
_DERIVED_DESTINATION = "prod"


class DestinationGuardError(RuntimeError):
    """A destination check failed. The message is meant to be printed whole."""


def _fail(destination: str, db: Path, findings: list[str]) -> None:
    detail = "\n".join(f"  - {f}" for f in findings)
    raise DestinationGuardError(
        f"\n{'=' * 78}\n"
        f"DESTINATION CHECK FAILED for {destination!r}\n"
        f"  database: {db}\n"
        f"{'=' * 78}\n"
        f"{detail}\n"
        f"{'=' * 78}\n"
        f"{_ABORT_BANNER}\n"
        f"{'=' * 78}"
    )


def destinations_from_configs(config_root: Path) -> dict[str, set[str]]:
    """Read `deployTo` straight from the on-disk dataset configs.

    Deliberately a second, independent parse rather than a call into
    processing.config: this is the value the *checkout* declares, which is what
    we are cross-checking the DB against.
    """
    out: dict[str, set[str]] = {}
    for yaml_path in sorted(config_root.rglob("config.yaml")):
        loaded = yaml.safe_load(yaml_path.read_text())
        if not loaded:
            continue
        deploy_to = loaded.get("deployTo")
        if not isinstance(deploy_to, list):
            raise DestinationGuardError(
                f"{yaml_path}: missing or malformed `deployTo`; cannot verify a "
                f"destination against configs that do not declare one."
            )
        for table in loaded.get("tables", []) or []:
            name = table.get("table")
            if name:
                out[name] = {d for d in deploy_to if d in INSTANCE_ORDER}
    return out


def _table_names(conn: sqlite3.Connection, schema: str = "main") -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table'"
        )
    }


def _scan_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    forbidden: set[str],
    findings: list[str],
    *,
    split: bool = False,
) -> None:
    """Flag any row of `table.column` naming a forbidden table.

    `split` handles the comma-joined columns (central_gene.dataset_names,
    overview_matrix_expansions.source_tables), where one cell can carry many
    table names.
    """
    if table not in _table_names(conn):
        return
    try:
        rows = conn.execute(f'SELECT DISTINCT "{column}" FROM "{table}"').fetchall()
    except sqlite3.Error:
        return  # column absent in an older DB — nothing to scan
    for (value,) in rows:
        if not value:
            continue
        text = str(value)
        candidates = (
            {p.strip() for p in text.split(",")} if split else {text}
        )
        for hit in sorted(candidates & forbidden):
            findings.append(
                f"{table}.{column} references non-member table {hit!r}"
            )


def _scan_substring(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    forbidden: set[str],
    findings: list[str],
) -> None:
    """Flag rows whose value *contains* a forbidden table name.

    For paths and JSON blobs (export_files.path,
    overview_matrix_info.expanded_source_tables) where the name is embedded
    rather than being the whole cell.
    """
    if table not in _table_names(conn):
        return
    try:
        rows = conn.execute(f'SELECT DISTINCT "{column}" FROM "{table}"').fetchall()
    except sqlite3.Error:
        return
    for (value,) in rows:
        if not value:
            continue
        text = str(value)
        for name in sorted(forbidden):
            if name in text:
                findings.append(
                    f"{table}.{column} value {text!r} contains non-member "
                    f"table {name!r}"
                )


def _scan_export_zip(
    conn: sqlite3.Connection, forbidden: set[str], findings: list[str]
) -> None:
    """Crack open all-tables.zip and check its member list.

    The zip is built from the other export_files blobs, so it is correct by
    construction — but it is also the single artifact a user downloads, so it
    gets checked directly rather than by inference.

    Only names are checked, not blob *contents*. Contents are generated from
    the file's own data_tables and so cannot name a non-member table, and
    substring-scanning them would false-positive on ordinary column names: a
    prod dataset legitimately has a `sfari_gene` annotation column while
    `sfari_*` is dev-only.
    """
    if "export_files" not in _table_names(conn):
        return
    row = conn.execute(
        "SELECT content FROM export_files WHERE path = 'all-tables.zip'"
    ).fetchone()
    if not row or not row[0]:
        return
    try:
        with zipfile.ZipFile(io.BytesIO(row[0])) as zf:
            members = zf.namelist()
    except zipfile.BadZipFile:
        findings.append("export_files: all-tables.zip is not a readable zip")
        return
    for member in members:
        for name in sorted(forbidden):
            if name in member:
                findings.append(
                    f"all-tables.zip contains {member!r}, which names "
                    f"non-member table {name!r}"
                )


def _verify_derived_db(
    path: Path,
    label: str,
    columns: list[tuple[str, str, bool]],
    allowed: set[str],
    all_known: set[str],
    findings: list[str],
    main_uuid: str | None,
) -> None:
    """Check a `-meta` / `-overview` sibling, if present.

    Same rule on every instance: these are computed once from prod-labelled
    inputs and copied verbatim, so they may name prod-labelled tables only.
    """
    if not path.exists():
        return
    forbidden = all_known - allowed
    # Collect into a local list so this pass's findings can be labelled with the
    # file they came from without touching findings from earlier passes.
    local: list[str] = []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for table, column, split in columns:
            _scan_column(conn, table, column, forbidden, local, split=split)
        # expanded_source_tables is a JSON list, so the name is embedded in the
        # cell rather than being the whole of it.
        _scan_substring(conn, "overview_matrix_info", "value", forbidden, local)
        derived_uuid = None
        for info_table in ("meta_analysis_info", "overview_matrix_info"):
            if info_table in _table_names(conn):
                row = conn.execute(
                    f"SELECT value FROM {info_table} "
                    f"WHERE key = 'source_build_uuid'"
                ).fetchone()
                if row:
                    derived_uuid = row[0]
        if main_uuid and derived_uuid and derived_uuid != main_uuid:
            local.append(
                f"built from main DB build {derived_uuid!r} but this main DB "
                f"is build {main_uuid!r} — the two would be served together "
                f"while describing different dataset sets"
            )
    finally:
        conn.close()
    findings.extend(f"{label}: {finding}" for finding in local)


def verify_destination(
    db: Path,
    destination: str,
    *,
    config_root: Path | None = None,
    context: str = "verify",
    check_derived: bool = True,
) -> None:
    """Raise DestinationGuardError unless `db` is exactly right for `destination`.

    `config_root` is the checkout's data/datasets directory; when given, its
    `deployTo` lists are the source of truth and the DB's own
    `dataset_destinations` is cross-checked against them. When omitted (e.g.
    verifying a DB whose checkout isn't reachable) the DB's own labels are used
    alone, which is a weaker check — it can still catch a leak, but not a DB
    built from stale configs.
    """
    if destination not in INSTANCE_ORDER:
        raise DestinationGuardError(
            f"unknown destination {destination!r}; expected one of "
            f"{', '.join(INSTANCE_ORDER)}"
        )
    if not db.exists():
        raise DestinationGuardError(f"database not found: {db}")

    findings: list[str] = []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        if "dataset_destinations" not in _table_names(conn):
            raise DestinationGuardError(
                f"{db} has no `dataset_destinations` table — it predates #225 "
                f"and its contents cannot be attributed to a destination. "
                f"Rebuild it with `sspsygene load-db` before promoting.\n"
                f"{_ABORT_BANNER}"
            )

        db_labels: dict[str, set[str]] = {}
        for table_name, dest in conn.execute(
            "SELECT table_name, destination FROM dataset_destinations"
        ):
            db_labels.setdefault(table_name, set()).add(dest)

        built = {
            row[0] for row in conn.execute("SELECT table_name FROM data_tables")
        }

        # ── Source of truth, and the cross-check that makes it independent ──
        if config_root is not None:
            config_labels = destinations_from_configs(config_root)
            all_known = set(config_labels)
            allowed = {t for t, d in config_labels.items() if destination in d}

            for table_name in sorted(set(db_labels) | set(config_labels)):
                in_db = db_labels.get(table_name)
                in_cfg = config_labels.get(table_name)
                if in_db is None:
                    # A dataset declared on disk but absent from this DB is only
                    # a problem if it should be here; the equality check below
                    # reports that with a clearer message.
                    continue
                if in_cfg is None:
                    findings.append(
                        f"dataset_destinations names table {table_name!r}, "
                        f"which no config.yaml in {config_root} declares — the "
                        f"DB was built from different configs than this checkout"
                    )
                elif in_db != in_cfg:
                    findings.append(
                        f"table {table_name!r}: DB says deployTo="
                        f"{sorted(in_db)} but {config_root} says "
                        f"{sorted(in_cfg)} — the DB was built from different "
                        f"configs than this checkout"
                    )
        else:
            all_known = set(db_labels)
            allowed = {t for t, d in db_labels.items() if destination in d}

        # ── Equality, in both directions ───────────────────────────────────
        leaked = built - allowed
        missing = allowed - built
        if leaked:
            findings.append(
                f"data_tables contains {len(leaked)} table(s) NOT labelled for "
                f"{destination}: {sorted(leaked)}"
            )
        if missing:
            findings.append(
                f"data_tables is MISSING {len(missing)} table(s) labelled for "
                f"{destination}: {sorted(missing)}"
            )

        # ── Deny-scan every place a table name can hide ─────────────────────
        forbidden = all_known - allowed
        if forbidden:
            present_objects = _table_names(conn)
            for hit in sorted(forbidden & present_objects):
                findings.append(
                    f"sqlite_master: the data table {hit!r} is physically "
                    f"present in the file"
                )
            for hit in sorted(
                name
                for name in forbidden
                for obj in present_objects
                if obj.startswith(f"{name}__")
            ):
                findings.append(
                    f"sqlite_master: a link table of non-member {hit!r} is "
                    f"physically present in the file"
                )

            _scan_column(conn, "data_tables", "table_name", forbidden, findings)
            _scan_column(
                conn, "changelog_entries", "table_name", forbidden, findings
            )
            _scan_column(
                conn, "dataset_destinations", "table_name", forbidden, findings
            )
            _scan_column(
                conn,
                "central_gene",
                "dataset_names",
                forbidden,
                findings,
                split=True,
            )
            _scan_column(
                conn, "central_gene_usage", "table_name", forbidden, findings
            )
            _scan_substring(conn, "export_files", "path", forbidden, findings)
            _scan_export_zip(conn, forbidden, findings)

        main_uuid = read_build_uuid(conn)
    finally:
        conn.close()

    # ── The derived DBs, under the destination-independent prod-only rule ───
    if check_derived:
        prod_allowed = {
            t
            for t, d in (
                destinations_from_configs(config_root)
                if config_root is not None
                else db_labels
            ).items()
            if _DERIVED_DESTINATION in d
        }
        stem, suffix = db.stem, db.suffix
        _verify_derived_db(
            db.with_name(f"{stem}-meta{suffix}"),
            "meta DB",
            [("combined_pvalue_groups", "source_table_names", True)],
            prod_allowed,
            all_known,
            findings,
            main_uuid,
        )
        _verify_derived_db(
            db.with_name(f"{stem}-overview{suffix}"),
            "overview DB",
            [
                ("overview_matrix_expansions", "source_tables", True),
                ("overview_matrix_expanded_columns", "source_table", False),
                ("overview_matrix_expanded_cells", "source_table", False),
            ],
            prod_allowed,
            all_known,
            findings,
            main_uuid,
        )

    if findings:
        _fail(destination, db, findings)

    logger.info(
        "%s: %s is valid for destination %r (%d data tables)",
        context,
        db.name,
        destination,
        len(built),
    )
