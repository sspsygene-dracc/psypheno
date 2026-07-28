"""Unit tests for the overview-matrix materialization (#222).

The fixture is a hand-built miniature of the real DB: three labeled source
tables covering the behaviours that are easy to get subtly wrong — status
precedence, an assay that maps to two modalities, control exclusion, the
group-map shortcut and its fallback, tie-breaking in the column sort, and the
-log10 clamp.
"""

import json
import math
import sqlite3

import pytest

from processing.overview_matrix import (
    NEG_LOG_P_MAX,
    NEG_LOG_P_MIN,
    _neg_log_p,
    materialize_overview_matrix,
)


MODALITIES = [
    ("expression", '["expression"]', 0),
    ("behavior", '["behavior"]', 1),
    ("perturb_seq", '["perturbation_deg", "perturbation"]', 2),
    ("perturb_fish", '["spatial"]', 3),
]

# id, symbol, kind
GENES = [
    (1, "AAA", "gene"),
    (2, "BBB", "gene"),
    (3, "CCC", "gene"),
    (4, "DDD", "gene"),
    (9, "CTRL", "control"),
]


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE modalities (key TEXT PRIMARY KEY, label TEXT, "
        "assay_types TEXT, always_show INTEGER NOT NULL DEFAULT 0, "
        "sort_order INTEGER NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO modalities (key, label, assay_types, sort_order) "
        "VALUES (?, ?, ?, ?)",
        [(key, key.title(), assays, order) for key, assays, order in MODALITIES],
    )
    conn.execute(
        "CREATE TABLE central_gene (id INTEGER PRIMARY KEY, human_symbol TEXT, "
        "kind TEXT NOT NULL DEFAULT 'gene')"
    )
    conn.executemany("INSERT INTO central_gene VALUES (?, ?, ?)", GENES)
    conn.execute(
        "CREATE TABLE data_tables (table_name TEXT, assay TEXT, "
        "pvalue_column TEXT, fdr_column TEXT, link_tables TEXT, "
        "include_in_overview_matrix INTEGER NOT NULL DEFAULT 0, "
        "expand_in_overview_matrix INTEGER NOT NULL DEFAULT 0, "
        "short_label TEXT)"
    )
    return conn


def _add_link(conn: sqlite3.Connection, name: str, pairs: list[tuple[int, int]]) -> None:
    conn.execute(
        f"CREATE TABLE {name} (central_gene_id INTEGER NOT NULL, "
        "id INTEGER NOT NULL, PRIMARY KEY (central_gene_id, id)) WITHOUT ROWID"
    )
    conn.executemany(f"INSERT INTO {name} VALUES (?, ?)", pairs)


def _register(
    conn: sqlite3.Connection,
    table_name: str,
    assay: str,
    link_tables: str,
    *,
    pvalue_column: str | None = None,
    fdr_column: str | None = None,
    expand: int = 0,
) -> None:
    conn.execute(
        "INSERT INTO data_tables (table_name, assay, pvalue_column, fdr_column, "
        "link_tables, include_in_overview_matrix, expand_in_overview_matrix, "
        "short_label) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
        (table_name, assay, pvalue_column, fdr_column, link_tables, expand, table_name),
    )


@pytest.fixture
def conn() -> sqlite3.Connection:
    """A miniature dataset DB with three overview-matrix source tables."""
    conn = _make_db()

    # 1. A perturbation-DEG table -> perturb_seq. Gene 1 has a significant row,
    #    gene 2 only non-significant p-values, gene 3 only NULLs, and the
    #    control gene 9 has a significant row that must never surface.
    conn.execute("CREATE TABLE deg (id INTEGER, p_value REAL, fdr REAL)")
    conn.executemany(
        "INSERT INTO deg VALUES (?, ?, ?)",
        [(1, 0.01, 0.02), (2, 0.4, 0.5), (3, None, None), (4, 0.001, 0.001)],
    )
    _add_link(conn, "deg__perturbed", [(1, 1), (2, 2), (3, 3), (9, 4)])
    _register(
        conn, "deg", "perturbation_deg", "gene:deg__perturbed:perturbed",
        pvalue_column="p_value", fdr_column="fdr",
    )

    # 2. A spatial table with no stat columns at all -> can only ever be
    #    "assayed_null", and its assay maps to *two* modalities.
    conn.execute("CREATE TABLE fish (id INTEGER)")
    conn.executemany("INSERT INTO fish VALUES (?)", [(1,), (2,)])
    _add_link(conn, "fish__perturbed", [(4, 1), (4, 2)])
    _register(conn, "fish", "spatial,perturbation", "gene:fish__perturbed:perturbed")

    # 3. An expanded expression table: 3 regions plus one region with no
    #    resolvable gene, 3 target genes.
    conn.execute(
        "CREATE TABLE expr (id INTEGER, region TEXT, target_gene TEXT, "
        "p_value REAL, adj_p REAL)"
    )
    rows = [
        # (id, region, target, p, fdr)
        (1, "R1", "T1", 1e-30, 0.001),   # clamped to NEG_LOG_P_MAX
        (2, "R2", "T1", 0.002, 0.01),
        (3, "R3", "T1", 0.003, 0.02),
        (4, "", "T1", 0.5, 0.9),
        (5, "R1", "T2", 0.5, 0.9),       # significant nowhere
        (6, "R2", "T2", 0.6, 0.9),
        (7, "R3", "T2", 0.7, 0.9),
        (8, "", "T2", 0.8, 0.9),
        (9, "R1", "T3", 0.004, 0.01),
        (10, "R2", "T3", 0.9, 0.9),      # present but not significant
        (11, "R3", "T3", 0.9, 0.9),
        (12, "", "T3", 0.004, 0.01),     # gene-less region: does NOT count
    ]
    conn.executemany("INSERT INTO expr VALUES (?, ?, ?, ?, ?)", rows)
    # R1 -> genes 1, 2 (and the control 9); R2 -> gene 2; R3 -> gene 3;
    # "" -> nothing.
    region_genes = {"R1": [1, 2, 9], "R2": [2], "R3": [3], "": []}
    pairs = [
        (gene_id, row[0])
        for row in rows
        for gene_id in region_genes[row[1]]
    ]
    _add_link(conn, "expr__region", pairs)
    _register(
        conn,
        "expr",
        "expression",
        "target_gene:expr__gene:target,region:expr__region:perturbed",
        pvalue_column="p_value",
        fdr_column="adj_p",
        expand=1,
    )
    return conn


def _status_cells(conn: sqlite3.Connection) -> dict[tuple[int, str], tuple]:
    return {
        (gene_id, modality): (status, count, json.loads(table_names))
        for gene_id, modality, status, count, table_names in conn.execute(
            "SELECT central_gene_id, modality_key, status, count, table_names "
            "FROM overview_matrix_status_cells"
        )
    }


def test_status_precedence_and_control_exclusion(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=1)
    cells = _status_cells(conn)

    assert cells[(1, "perturb_seq")] == ("significant", 1, ["deg"])
    # Both p and fdr are non-null but neither is < 0.05.
    assert cells[(2, "perturb_seq")] == ("data", 1, ["deg"])
    # Row present, every stat column NULL.
    assert cells[(3, "perturb_seq")] == ("assayed_null", 1, ["deg"])
    # The control gene never appears, in any modality.
    assert not any(gene_id == 9 for gene_id, _ in cells)

    genes = dict(
        conn.execute("SELECT central_gene_id, human_symbol FROM overview_matrix_genes")
    )
    assert genes == {1: "AAA", 2: "BBB", 3: "CCC", 4: "DDD"}


def test_assay_mapping_to_two_modalities(conn: sqlite3.Connection) -> None:
    """`spatial,perturbation` contributes the same counts to both columns."""
    materialize_overview_matrix(conn, min_groups=1)
    cells = _status_cells(conn)

    # No stat columns -> assayed_null over both of the table's 2 rows.
    assert cells[(4, "perturb_fish")] == ("assayed_null", 2, ["fish"])
    assert cells[(4, "perturb_seq")] == ("assayed_null", 2, ["fish"])


def test_expanded_columns_selection_and_order(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=1)
    columns = conn.execute(
        "SELECT column_value, n_sig_groups, min_p FROM overview_matrix_expanded_columns "
        "ORDER BY sort_rank"
    ).fetchall()

    # T1 is significant in R1/R2/R3; T3 only in R1, because its other
    # significant region ("") resolves to no perturbed gene and so cannot
    # qualify a column. T2 is significant nowhere and is not a column at all.
    assert [c[0] for c in columns] == ["T1", "T3"]
    assert [c[1] for c in columns] == [3, 1]

    # A higher floor drops the weaker column entirely.
    materialize_overview_matrix(conn, min_groups=3)
    assert [
        row[0]
        for row in conn.execute(
            "SELECT column_value FROM overview_matrix_expanded_columns"
        )
    ] == ["T1"]


def test_expanded_column_sort_breaks_ties_on_min_p(conn: sqlite3.Connection) -> None:
    """With equal region counts, the more significant column sorts first."""
    conn.executemany(
        "INSERT INTO expr VALUES (?, ?, ?, ?, ?)",
        [
            (13, "R1", "T4", 0.02, 0.01),
            (14, "R2", "T4", 0.03, 0.01),
            (15, "R3", "T4", 0.04, 0.01),
            (16, "", "T4", 0.05, 0.9),
        ],
    )
    new_row_genes = {13: [1, 2, 9], 14: [2], 15: [3], 16: []}
    conn.executemany(
        "INSERT INTO expr__region VALUES (?, ?)",
        [
            (gene_id, row_id)
            for row_id, gene_ids in new_row_genes.items()
            for gene_id in gene_ids
        ],
    )
    materialize_overview_matrix(conn, min_groups=1)

    ordered = [
        row[0]
        for row in conn.execute(
            "SELECT column_value FROM overview_matrix_expanded_columns ORDER BY sort_rank"
        )
    ]
    # T1 and T4 both hit 3 regions; T1's 1e-30 beats T4's 0.02.
    assert ordered[:2] == ["T1", "T4"]


def test_expanded_cells_take_the_min_p_across_regions(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=1)
    cells = {
        (gene_id, column): neg_log_p
        for gene_id, column, neg_log_p in conn.execute(
            "SELECT central_gene_id, column_value, neg_log_p "
            "FROM overview_matrix_expanded_cells"
        )
    }

    # Gene 1 only sits in R1, where T1's p is 1e-30 -> clamped.
    assert cells[(1, "T1")] == NEG_LOG_P_MAX
    # Gene 2 sits in R1 *and* R2; the stronger R1 p wins.
    assert cells[(2, "T1")] == NEG_LOG_P_MAX
    # Gene 3 only sits in R3.
    assert cells[(3, "T1")] == round(-math.log10(0.003), 3)
    # The gene-less "" region contributes no cells, and controls never appear.
    assert not any(gene_id == 9 for gene_id, _ in cells)
    # Gene 4 is perturbed only in the fish table, so it has no expression cells.
    assert not any(gene_id == 4 for gene_id, _ in cells)


def test_group_map_falls_back_when_the_shortcut_invariant_breaks(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    """Rows sharing a region value normally share a gene set; if one doesn't,
    the representative-row shortcut is wrong and the exact join must take over."""
    # Give row 2 (region R2) an extra gene that row 1's representative lacks.
    conn.execute("INSERT INTO expr__region VALUES (?, ?)", (4, 2))
    materialize_overview_matrix(conn, min_groups=1)

    assert "falling back to the exact join" in caplog.text
    cells = {
        (gene_id, column)
        for gene_id, column, _ in conn.execute(
            "SELECT central_gene_id, column_value, neg_log_p "
            "FROM overview_matrix_expanded_cells"
        )
    }
    # The exact join sees gene 4 in R2, which the shortcut would have missed.
    assert (4, "T1") in cells


def test_expansion_metadata_and_info(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=2)
    # Only T1 clears a floor of 2.
    assert conn.execute(
        "SELECT modality_key, column_prefix, source_tables, n_columns_total "
        "FROM overview_matrix_expansions"
    ).fetchall() == [("expression", "expr", "expr", 1)]

    info = dict(conn.execute("SELECT key, value FROM overview_matrix_info"))
    assert info["min_groups_floor"] == "2"
    assert json.loads(info["expanded_source_tables"]) == ["expr"]
    assert info["schema_version"] == "2"
    assert info["materialize_top_m"] == "200"


def test_rebuild_is_idempotent(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=1)
    first = _status_cells(conn)
    materialize_overview_matrix(conn, min_groups=1)
    assert _status_cells(conn) == first


def test_neg_log_p_clamp() -> None:
    assert _neg_log_p(0.1) == NEG_LOG_P_MIN
    assert _neg_log_p(0.5) == NEG_LOG_P_MIN  # below the floor, clamped up
    assert _neg_log_p(1e-30) == NEG_LOG_P_MAX
    assert _neg_log_p(0.0) == NEG_LOG_P_MAX  # underflowed p, not -inf
    assert _neg_log_p(0.001) == 3.0
    # Stored to 3 decimals: a color-ramp coordinate, not an analysis value.
    assert _neg_log_p(0.003) == 2.523
