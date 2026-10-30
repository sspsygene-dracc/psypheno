"""Unit tests for the overview-matrix materialization (#222, #213).

The fixture is a hand-built miniature of the real DB exercising every column
axis: a gene-target expansion (expression), an FDR-only gene expansion
(perturb-FISH → the `neglog_q` metric), a long-phenotype expansion, and a
wide-phenotype expansion. Status columns were removed in #213; every source
table is expanded.
"""

import json
import math
import sqlite3

import pytest

from processing.overview_matrix import (
    NEG_LOG_P_MAX,
    NEG_LOG_P_MIN,
    _neg_log_p,
    load_panel_symbols,
    materialize_overview_matrix,
    resolve_panel_gene_ids,
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

_DATA_TABLES_COLUMNS = (
    "table_name TEXT, assay TEXT, pvalue_column TEXT, fdr_column TEXT, "
    "link_tables TEXT, include_in_overview_matrix INTEGER NOT NULL DEFAULT 0, "
    "short_label TEXT, "
    "overview_matrix_phenotype_column TEXT, overview_matrix_phenotype_columns TEXT, "
    "overview_matrix_metric TEXT, overview_matrix_metric_domain TEXT"
)


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
    conn.execute(f"CREATE TABLE data_tables ({_DATA_TABLES_COLUMNS})")
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
    phenotype_column: str | None = None,
    phenotype_columns: list[str] | None = None,
    metric: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO data_tables (table_name, assay, pvalue_column, fdr_column, "
        "link_tables, include_in_overview_matrix, "
        "short_label, overview_matrix_phenotype_column, "
        "overview_matrix_phenotype_columns, overview_matrix_metric) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
        (
            table_name,
            assay,
            pvalue_column,
            fdr_column,
            link_tables,
            table_name,
            phenotype_column,
            json.dumps(phenotype_columns) if phenotype_columns else None,
            metric,
        ),
    )


def _add_gene_expr(conn: sqlite3.Connection) -> None:
    """An expanded expression table: 3 regions, one gene-less region, 3 targets."""
    conn.execute(
        "CREATE TABLE expr (id INTEGER, region TEXT, target_gene TEXT, "
        "p_value REAL, adj_p REAL)"
    )
    rows = [
        (1, "R1", "T1", 1e-30, 0.001),   # clamped to NEG_LOG_P_MAX
        (2, "R2", "T1", 0.002, 0.01),
        (3, "R3", "T1", 0.003, 0.02),
        (4, "", "T1", 0.5, 0.9),
        (5, "R1", "T2", 0.5, 0.9),       # significant nowhere
        (6, "R2", "T2", 0.6, 0.9),
        (7, "R3", "T2", 0.7, 0.9),
        (8, "", "T2", 0.8, 0.9),
        (9, "R1", "T3", 0.004, 0.01),
        (10, "R2", "T3", 0.9, 0.9),
        (11, "R3", "T3", 0.9, 0.9),
        (12, "", "T3", 0.004, 0.01),     # gene-less region: does NOT count
    ]
    conn.executemany("INSERT INTO expr VALUES (?, ?, ?, ?, ?)", rows)
    region_genes = {"R1": [1, 2, 9], "R2": [2], "R3": [3], "": []}
    pairs = [(g, row[0]) for row in rows for g in region_genes[row[1]]]
    _add_link(conn, "expr__region", pairs)
    _register(
        conn,
        "expr",
        "expression",
        "target_gene:expr__gene:target,region:expr__region:perturbed",
        pvalue_column="p_value",
        fdr_column="adj_p",
    )


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = _make_db()
    _add_gene_expr(conn)
    return conn


def _columns(conn: sqlite3.Connection, table: str | None = None):
    where = "" if table is None else f" WHERE source_table = '{table}'"
    return conn.execute(
        "SELECT column_value, n_sig_groups, metric, column_is_gene "
        f"FROM overview_matrix_expanded_columns{where} ORDER BY sort_rank"
    ).fetchall()


def _cells(conn: sqlite3.Connection, table: str):
    return {
        (gene_id, column): value
        for gene_id, column, value in conn.execute(
            "SELECT central_gene_id, column_value, value "
            f"FROM overview_matrix_expanded_cells WHERE source_table = '{table}'"
        )
    }


def _summary_column(conn: sqlite3.Connection, table: str):
    return conn.execute(
        "SELECT modality_key, column_prefix, base_metric, sig_rule, n_readouts_total "
        "FROM overview_matrix_summary_columns WHERE source_table = ?",
        (table,),
    ).fetchone()


def _summary_cells(conn: sqlite3.Connection, table: str):
    return {
        gene_id: (n_sig, n_measured, best)
        for gene_id, n_sig, n_measured, best in conn.execute(
            "SELECT central_gene_id, n_sig, n_measured, best_value "
            f"FROM overview_matrix_summary_cells WHERE source_table = \'{table}\'"
        )
    }


# --- gene-target axis (unchanged core behaviour) ---------------------------

def test_gene_columns_selection_order_and_metric(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=1)
    cols = _columns(conn, "expr")
    # T1 significant in R1/R2/R3; T3 only in R1 (its other sig region is gene-less);
    # T2 significant nowhere.
    assert [c[0] for c in cols] == ["T1", "T3"]
    assert [c[1] for c in cols] == [3, 1]
    # Gene-target columns carry the neglog_p metric and are flagged as genes.
    assert all(c[2] == "neglog_p" and c[3] == 1 for c in cols)

    # A higher floor drops the weaker column entirely.
    materialize_overview_matrix(conn, min_groups=3)
    assert [c[0] for c in _columns(conn, "expr")] == ["T1"]


def test_gene_rows_are_the_perturbed_genes_no_controls(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=1)
    genes = dict(
        conn.execute("SELECT central_gene_id, human_symbol FROM overview_matrix_genes")
    )
    # expr's perturbed link resolves R1->{1,2}, R2->{2}, R3->{3}; control 9 excluded.
    assert genes == {1: "AAA", 2: "BBB", 3: "CCC"}


def test_gene_cells_take_min_p_across_groups(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=1)
    cells = _cells(conn, "expr")
    assert cells[(1, "T1")] == NEG_LOG_P_MAX          # gene 1 sits only in R1 (1e-30)
    assert cells[(2, "T1")] == NEG_LOG_P_MAX          # gene 2 in R1 & R2; R1 wins
    assert cells[(3, "T1")] == round(-math.log10(0.003), 3)  # gene 3 only in R3
    assert not any(gene_id == 9 for gene_id, _ in cells)


def test_group_column_merges_rows_that_perturb_the_same_gene(
    conn: sqlite3.Connection,
) -> None:
    """Rows naming the same perturbed gene are ONE group, not two (#226).

    Gordon 2026 models SHANK3 loss twice — a 22q13.33 deletion and a point
    mutation — as two separate genotypes. Once the perturbed column holds the
    representative driver gene rather than the CNV's whole interval, both
    collapse to the same group value, so a target significant in only those
    two stays *below* the convergence floor instead of looking like it
    replicated across two independent perturbations.
    """
    conn.execute(
        "CREATE TABLE drv (id INTEGER, perturbed_gene TEXT, target_gene TEXT, "
        "p_value REAL, adj_p REAL)"
    )
    conn.executemany(
        "INSERT INTO drv VALUES (?, ?, ?, ?, ?)",
        [
            (1, "AAA", "T1", 0.001, 0.01),  # "deletion"       -> AAA
            (2, "AAA", "T1", 0.002, 0.01),  # "point mutation" -> AAA, same group
            (3, "BBB", "T1", 0.9, 0.9),     # the other gene: not significant
            (4, "AAA", "T2", 0.001, 0.01),
            (5, "BBB", "T2", 0.002, 0.01),  # T2 does converge across two genes
        ],
    )
    _add_link(conn, "drv__perturbed", [(1, 1), (1, 2), (1, 4), (2, 3), (2, 5)])
    _register(
        conn,
        "drv",
        "spatial",
        "perturbed_gene:drv__perturbed:perturbed,target_gene:drv__gene:target",
        pvalue_column="p_value",
        fdr_column="adj_p",
    )
    materialize_overview_matrix(conn, min_groups=2)
    # T1 is significant in both AAA rows, but they are one group -> below floor.
    assert _columns(conn, "drv") == [("T2", 2, "neglog_p", 1)]


# --- FDR-only gene axis -> neglog_q ---------------------------------------

def test_fdr_only_table_uses_neglog_q(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE fishx (id INTEGER, pgene TEXT, tgt TEXT, qval REAL)")
    conn.executemany(
        "INSERT INTO fishx VALUES (?, ?, ?, ?)",
        [(1, "AAA", "TF", 0.001), (2, "BBB", "TF", 0.01)],
    )
    _add_link(conn, "fishx__perturbed", [(1, 1), (2, 2)])
    _register(
        conn,
        "fishx",
        "spatial",
        "pgene:fishx__perturbed:perturbed,tgt:fishx__gene:target",
        fdr_column="qval",
    )
    materialize_overview_matrix(conn, min_groups=1)
    cols = _columns(conn, "fishx")
    assert cols == [("TF", 2, "neglog_q", 1)]


# --- long phenotype axis ---------------------------------------------------

def test_long_phenotype_shows_all_columns(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE beh (id INTEGER, pgene TEXT, param TEXT, pval REAL)")
    conn.executemany(
        "INSERT INTO beh VALUES (?, ?, ?, ?)",
        [
            (1, "AAA", "P1", 0.001),
            (2, "AAA", "P2", 0.5),
            (3, "AAA", "P3", 0.2),
            (4, "BBB", "P1", 0.01),
            (5, "BBB", "P2", 0.6),
            (6, "BBB", "P3", 0.9),
        ],
    )
    _add_link(conn, "beh__perturbed", [(1, 1), (1, 2), (1, 3), (2, 4), (2, 5), (2, 6)])
    _register(
        conn,
        "beh",
        "behavior",
        "pgene:beh__perturbed:perturbed",
        pvalue_column="pval",
        phenotype_column="param",
    )
    materialize_overview_matrix(conn, min_groups=2)  # floor ignored for phenotypes
    cols = _columns(conn, "beh")
    # All three params kept (show-all); P1 (sig in 2 genes) first, then P3/P2 by min p.
    assert [c[0] for c in cols] == ["P1", "P3", "P2"]
    assert all(c[2] == "neglog_p" and c[3] == 0 for c in cols)
    cells = _cells(conn, "beh")
    assert cells[(1, "P1")] == 3.0                       # -log10(0.001)
    assert cells[(2, "P1")] == round(-math.log10(0.01), 3)


# --- wide phenotype axis ---------------------------------------------------

def test_wide_phenotype_max_magnitude_aggregate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE wide (id INTEGER, cola REAL, colb REAL)")
    conn.executemany(
        "INSERT INTO wide VALUES (?, ?, ?)",
        [(1, 3.0, -1.0), (2, -5.0, 0.5), (3, 2.0, 4.0)],
    )
    # ids 1,2 -> gene AAA (two rows); id 3 -> gene BBB.
    _add_link(conn, "wide__perturbed", [(1, 1), (1, 2), (2, 3)])
    _register(
        conn,
        "wide",
        "behavior",
        "src:wide__perturbed:perturbed",
        phenotype_columns=["ColA", "ColB"],
        metric="signed_neglog_p",
    )
    materialize_overview_matrix(conn, min_groups=1)
    cols = _columns(conn, "wide")
    assert [c[0] for c in cols] == ["ColA", "ColB"]      # raw names as labels
    assert all(c[2] == "signed_neglog_p" and c[3] == 0 for c in cols)
    cells = _cells(conn, "wide")
    # AAA: ColA max|3, -5| = -5; ColB max|-1, 0.5| = -1. BBB: 2 and 4.
    assert cells[(1, "ColA")] == -5.0
    assert cells[(1, "ColB")] == -1.0
    assert cells[(2, "ColA")] == 2.0
    assert cells[(2, "ColB")] == 4.0


def test_long_phenotype_signed_metric_takes_sign_from_the_effect(
    conn: sqlite3.Connection,
) -> None:
    conn.execute(
        "CREATE TABLE beh (id INTEGER, pgene TEXT, param TEXT, pval REAL, beta REAL)"
    )
    conn.executemany(
        "INSERT INTO beh VALUES (?, ?, ?, ?, ?)",
        [
            (1, "AAA", "P1", 0.001, -2.0),
            (2, "AAA", "P1", 0.1, 3.0),
            (3, "BBB", "P1", 0.01, 1.0),
            (4, "BBB", "P2", 0.5, None),
        ],
    )
    _add_link(conn, "beh__perturbed", [(1, 1), (1, 2), (2, 3), (2, 4)])
    _register(
        conn,
        "beh",
        "behavior",
        "pgene:beh__perturbed:perturbed",
        pvalue_column="pval",
        phenotype_column="param",
        metric="signed_neglog_p",
    )
    conn.execute("ALTER TABLE data_tables ADD COLUMN effect_column TEXT")
    conn.execute("UPDATE data_tables SET effect_column = 'beta'")
    materialize_overview_matrix(conn, min_groups=1)
    cols = _columns(conn, "beh")
    assert [c[0] for c in cols] == ["P1"]  # P2's only row has no effect
    assert cols[0][2] == "signed_neglog_p"
    cells = _cells(conn, "beh")
    # AAA keeps its strongest row, with that row's sign.
    assert cells[(1, "P1")] == -3.0
    assert cells[(2, "P1")] == 2.0


def _two_wide_tables(conn: sqlite3.Connection, rows_a: list, rows_b: list) -> None:
    for name, rows in (("wide_a", rows_a), ("wide_b", rows_b)):
        conn.execute(f"CREATE TABLE {name} (id INTEGER, cola REAL, colb REAL, colc REAL, cold REAL)")
        conn.executemany(f"INSERT INTO {name} VALUES (?, ?, ?, ?, ?)", rows)
        _add_link(conn, f"{name}__perturbed", [(r[0], r[0]) for r in rows])
        _register(
            conn,
            name,
            "behavior",
            f"src:{name}__perturbed:perturbed",
            phenotype_columns=["ColA", "ColB", "ColC", "ColD"],
            metric="signed_neglog_p",
        )


def _shared(conn: sqlite3.Connection) -> set[tuple[str, str, int, str]]:
    return set(
        conn.execute(
            "SELECT source_table, column_value, central_gene_id, shared_with_table "
            "FROM overview_matrix_shared_cells"
        )
    )


def test_shared_cells_mark_repeated_values_per_gene(
    conn: sqlite3.Connection,
) -> None:
    """AAA repeats across tables under other column names; BBB is new data."""
    _two_wide_tables(
        conn,
        [(1, 1.5, 2.5, -3.5, 0.2), (2, 1.0, 1.1, 1.2, 1.3)],
        [(1, 2.5, -1.5, 3.5, 0.9), (2, 4.0, 4.1, 4.2, 4.3)],
    )
    materialize_overview_matrix(conn, min_groups=1)
    shared = _shared(conn)
    assert ("wide_b", "ColA", 1, "wide_a") in shared
    assert ("wide_a", "ColC", 1, "wide_b") in shared
    assert {row[2] for row in shared} == {1}
    assert not any(row[1] == "ColD" for row in shared)


def test_a_few_chance_matches_are_not_shared_data(conn: sqlite3.Connection) -> None:
    _two_wide_tables(
        conn,
        [(1, 1.5, 2.5, 3.5, 0.2)],
        [(1, 1.5, 2.5, 9.0, 9.1)],
    )
    materialize_overview_matrix(conn, min_groups=1)
    assert _shared(conn) == set()


# --- per-dataset summary column (#234) -------------------------------------

def test_summary_counts_every_readout_not_just_the_columns(
    conn: sqlite3.Connection,
) -> None:
    """The breadth count spans readouts that never become columns.

    T2 is significant nowhere, so it is not a materialized column at any floor —
    but it *was* measured, and a summary that only walked the materialized
    columns would report 2 readouts instead of 3.
    """
    materialize_overview_matrix(conn, min_groups=1)
    assert [c[0] for c in _columns(conn, "expr")] == ["T1", "T3"]
    assert _summary_column(conn, "expr") == (
        "expression",
        "expr",
        "neglog_p",
        "fdr<0.05",
        3,
    )
    cells = _summary_cells(conn, "expr")
    # Gene 1 sits only in R1: T1 (1e-30) and T3 (0.004) significant, T2 not.
    assert cells[1] == (2, 3, NEG_LOG_P_MAX)
    # Gene 3 sits only in R3: T1 alone is significant there (FDR 0.02).
    assert cells[3] == (1, 3, round(-math.log10(0.003), 3))


def test_summary_counts_each_readout_once_per_gene(conn: sqlite3.Connection) -> None:
    """A gene in several perturbed groups must not count a readout twice.

    Gene 2 sits in both R1 and R2, and T1 is significant in each. Counting
    per (group, target) row rather than per distinct target would report 3
    significant readouts out of 5 measured instead of 2 out of 3.
    """
    materialize_overview_matrix(conn, min_groups=1)
    assert _summary_cells(conn, "expr")[2] == (2, 3, NEG_LOG_P_MAX)


def test_summary_survives_a_floor_that_drops_every_column(
    conn: sqlite3.Connection,
) -> None:
    """No column clears the bar, so the expansion returns early — the summary
    is written before that point and still describes the dataset."""
    materialize_overview_matrix(conn, min_groups=4)
    assert _columns(conn, "expr") == []
    assert conn.execute("SELECT COUNT(*) FROM overview_matrix_expansions").fetchone() == (0,)
    assert _summary_column(conn, "expr")[4] == 3
    assert _summary_cells(conn, "expr")[1] == (2, 3, NEG_LOG_P_MAX)


def test_summary_excludes_controls_and_off_panel_genes(
    conn: sqlite3.Connection,
) -> None:
    materialize_overview_matrix(conn, min_groups=1)
    assert 9 not in _summary_cells(conn, "expr")  # CTRL perturbs R1
    materialize_overview_matrix(conn, min_groups=1, panel_gene_ids={1, 3})
    assert sorted(_summary_cells(conn, "expr")) == [1, 3]


def test_summary_on_the_wide_axis_uses_a_nominal_p_rule(
    conn: sqlite3.Connection,
) -> None:
    """The wide axis carries a signed -log10(nominal p), not an FDR, so its
    count is taken against |value| >= -log10(0.05) and says so."""
    conn.execute("CREATE TABLE wide (id INTEGER, cola REAL, colb REAL)")
    conn.executemany(
        "INSERT INTO wide VALUES (?, ?, ?)",
        [(1, 3.0, -1.0), (2, -5.0, 0.5), (3, 2.0, 4.0)],
    )
    _add_link(conn, "wide__perturbed", [(1, 1), (1, 2), (2, 3)])
    _register(
        conn,
        "wide",
        "behavior",
        "src:wide__perturbed:perturbed",
        phenotype_columns=["ColA", "ColB"],
        metric="signed_neglog_p",
    )
    materialize_overview_matrix(conn, min_groups=1)
    assert _summary_column(conn, "wide") == (
        "behavior",
        "beh",
        "signed_neglog_p",
        "nominal_p<0.05",
        2,
    )
    cells = _summary_cells(conn, "wide")
    # AAA: ColA -5 clears the bar, ColB -1 does not; strongest is the -5.
    assert cells[1] == (1, 2, -5.0)
    # BBB: both clear it; strongest by magnitude is 4.
    assert cells[2] == (2, 2, 4.0)


# --- group-map shortcut fallback (gene axis) -------------------------------

def test_group_map_falls_back_when_shortcut_invariant_breaks(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    conn.execute("INSERT INTO expr__region VALUES (?, ?)", (4, 2))
    materialize_overview_matrix(conn, min_groups=1)
    assert "falling back to the exact join" in caplog.text
    assert (4, "T1") in _cells(conn, "expr")


# --- metadata + idempotency ------------------------------------------------

def test_expansion_metadata_and_info(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=2)
    assert conn.execute(
        "SELECT modality_key, column_prefix, source_tables, n_columns_total "
        "FROM overview_matrix_expansions"
    ).fetchall() == [("expression", "expr", "expr", 1)]

    info = dict(conn.execute("SELECT key, value FROM overview_matrix_info"))
    assert info["min_groups_floor"] == "2"
    assert json.loads(info["expanded_source_tables"]) == ["expr"]
    assert info["schema_version"] == "7"
    assert info["materialize_top_m"] == "200"


def test_rebuild_is_idempotent(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=1)
    first = _columns(conn)
    materialize_overview_matrix(conn, min_groups=1)
    assert _columns(conn) == first


def test_neg_log_p_clamp() -> None:
    assert _neg_log_p(0.1) == NEG_LOG_P_MIN
    assert _neg_log_p(0.5) == NEG_LOG_P_MIN
    assert _neg_log_p(1e-30) == NEG_LOG_P_MAX
    assert _neg_log_p(0.0) == NEG_LOG_P_MAX
    assert _neg_log_p(0.001) == 3.0
    assert _neg_log_p(0.003) == 2.523


# --- SSPsyGene panel row filter (#228) -------------------------------------


def test_panel_filter_restricts_rows_and_cells(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=1, panel_gene_ids={1, 3})
    genes = dict(
        conn.execute("SELECT central_gene_id, human_symbol FROM overview_matrix_genes")
    )
    # Gene 2 is perturbed but off-panel, so it is neither a row nor a cell.
    assert genes == {1: "AAA", 3: "CCC"}
    assert {gene_id for gene_id, _ in _cells(conn, "expr")} <= {1, 3}


def test_panel_filter_excludes_controls_even_if_listed(
    conn: sqlite3.Connection,
) -> None:
    # A control guide named on the panel must still never become a row.
    materialize_overview_matrix(conn, min_groups=1, panel_gene_ids={1, 9})
    genes = dict(
        conn.execute("SELECT central_gene_id, human_symbol FROM overview_matrix_genes")
    )
    assert genes == {1: "AAA"}


def test_no_panel_keeps_every_non_control_gene(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=1, panel_gene_ids=None)
    genes = dict(
        conn.execute("SELECT central_gene_id, human_symbol FROM overview_matrix_genes")
    )
    assert genes == {1: "AAA", 2: "BBB", 3: "CCC"}


def test_panel_filter_recorded_in_info(conn: sqlite3.Connection) -> None:
    materialize_overview_matrix(conn, min_groups=1, panel_gene_ids={1, 3})
    info = dict(conn.execute("SELECT key, value FROM overview_matrix_info"))
    assert info["sspsygene_panel_filtered"] == "1"
    assert info["sspsygene_panel_gene_count"] == "2"

    materialize_overview_matrix(conn, min_groups=1, panel_gene_ids=None)
    info = dict(conn.execute("SELECT key, value FROM overview_matrix_info"))
    assert info["sspsygene_panel_filtered"] == "0"


def test_resolve_panel_gene_ids_falls_back_to_synonyms(
    conn: sqlite3.Connection,
) -> None:
    conn.execute(
        "CREATE TABLE extra_gene_synonyms (central_gene_id INTEGER, synonym TEXT)"
    )
    # The consortium sheet carries retired symbols (SUV420H1 -> KMT5B); resolving
    # only on human_symbol would silently drop the gene from the matrix.
    conn.execute("INSERT INTO extra_gene_synonyms VALUES (2, 'OLD_BBB')")
    assert resolve_panel_gene_ids(conn, ["AAA", "OLD_BBB"]) == {1, 2}


def test_resolve_panel_gene_ids_skips_unknown_symbols(
    conn: sqlite3.Connection,
) -> None:
    conn.execute(
        "CREATE TABLE extra_gene_synonyms (central_gene_id INTEGER, synonym TEXT)"
    )
    assert resolve_panel_gene_ids(conn, ["AAA", "NOT_A_GENE"]) == {1}


def test_load_panel_symbols_skips_comments_and_blanks(tmp_path) -> None:
    path = tmp_path / "sspsygene_genes.txt"
    path.write_text("# provenance header\n\nAAA\nBBB\n\n# trailing note\nCCC\n")
    assert load_panel_symbols(path) == ["AAA", "BBB", "CCC"]


def test_load_panel_symbols_rejects_an_empty_list(tmp_path) -> None:
    path = tmp_path / "sspsygene_genes.txt"
    path.write_text("# only comments\n\n")
    with pytest.raises(ValueError, match="no symbols"):
        load_panel_symbols(path)


# --- destination scope (#225, #241) -----------------------------------------

def _label_destinations(conn: sqlite3.Connection, table: str, *dests: str) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dataset_destinations "
        "(dataset TEXT, table_name TEXT, destination TEXT)"
    )
    conn.executemany(
        "INSERT INTO dataset_destinations VALUES (?, ?, ?)",
        [("ds", table, d) for d in dests],
    )


def test_default_build_uses_prod_labelled_tables_only(
    conn: sqlite3.Connection,
) -> None:
    _label_destinations(conn, "expr", "dev", "int")
    materialize_overview_matrix(conn, min_groups=1)
    assert _columns(conn, "expr") == []
    info = dict(conn.execute("SELECT key, value FROM overview_matrix_info"))
    assert info["destination_scope"] == "prod"


def test_all_destinations_build_includes_non_prod_tables(
    conn: sqlite3.Connection,
) -> None:
    _label_destinations(conn, "expr", "dev", "int")
    materialize_overview_matrix(conn, min_groups=1, all_destinations=True)
    assert [c[0] for c in _columns(conn, "expr")] == ["T1", "T3"]
    info = dict(conn.execute("SELECT key, value FROM overview_matrix_info"))
    assert info["destination_scope"] == "all"
    assert json.loads(info["expanded_source_tables"]) == ["expr"]


# --- significant-only tables: inferred tested universe ----------------------


def _add_significant_only_screen(
    conn: sqlite3.Connection, *, tested: list[str] | None = None, contexts=("ctx",)
) -> None:
    """A pooled screen that published only hits, in two cell types.

    Perturbations P_AAA (gene 1), P_BBB (gene 2), P_CCC (gene 3). Every row is
    significant. Cell type X: T1 hit for P_AAA and P_BBB, T2 hit for P_AAA.
    Cell type Y: T3 hit for P_CCC only. So P_BBB (tested in X) was measured on
    T1 + T2, but not T3 (measured only in Y, where P_BBB has no row).
    """
    conn.execute(
        "CREATE TABLE screen (id INTEGER, pert TEXT, target TEXT, ctx TEXT, "
        "p REAL, fdr REAL)"
    )
    rows = [
        (1, "P_AAA", "T1", "X", 1e-6, 0.001),
        (2, "P_BBB", "T1", "X", 1e-5, 0.01),
        (3, "P_AAA", "T2", "X", 1e-4, 0.02),
        (4, "P_CCC", "T3", "Y", 1e-4, 0.03),
    ]
    conn.executemany("INSERT INTO screen VALUES (?, ?, ?, ?, ?, ?)", rows)
    pert_gene = {"P_AAA": 1, "P_BBB": 2, "P_CCC": 3}
    _add_link(conn, "screen__pert", [(pert_gene[r[1]], r[0]) for r in rows])
    _register(
        conn,
        "screen",
        "perturbation_deg",
        "target:screen__gene:target,pert:screen__pert:perturbed",
        pvalue_column="p",
        fdr_column="fdr",
    )
    for col in ("significant_only", "gene_species"):
        try:
            conn.execute(f"ALTER TABLE data_tables ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    conn.execute(
        "UPDATE data_tables SET significant_only = ?, gene_species = 'human' "
        "WHERE table_name = 'screen'",
        (
            json.dumps(
                {"context_columns": list(contexts), "tested_perturbations": tested or []}
            ),
        ),
    )


def _inferred_basis(conn: sqlite3.Connection, table: str) -> dict[tuple[int, str], str]:
    return {
        (gene_id, column): basis
        for gene_id, column, basis in conn.execute(
            "SELECT central_gene_id, column_value, basis FROM overview_matrix_inferred_cells "
            "WHERE source_table = ?",
            (table,),
        )
    }


def _inferred(conn: sqlite3.Connection, table: str) -> set[tuple[int, str]]:
    return {
        (gene_id, column)
        for gene_id, column in conn.execute(
            "SELECT central_gene_id, column_value FROM overview_matrix_inferred_cells "
            "WHERE source_table = ?",
            (table,),
        )
    }


def _summary_inferred(conn: sqlite3.Connection, table: str) -> dict[int, tuple[int, int, int]]:
    return {
        gene_id: (n_sig, n_measured, n_inferred)
        for gene_id, n_sig, n_measured, n_inferred in conn.execute(
            "SELECT central_gene_id, n_sig, n_measured, n_inferred "
            "FROM overview_matrix_summary_cells WHERE source_table = ?",
            (table,),
        )
    }


def test_infer_measured_readouts_is_context_aware() -> None:
    from processing.overview_matrix import infer_measured_readouts

    rows = [("a", "X", "T1"), ("b", "X", "T1"), ("a", "X", "T2"), ("c", "Y", "T3")]
    measured = infer_measured_readouts(rows, {"a": [1], "b": [2], "c": [3]}, set())
    assert measured == {1: {"T1", "T2"}, 2: {"T1", "T2"}, 3: {"T3"}}


def test_infer_measured_readouts_library_gene_assumed_tested_everywhere() -> None:
    from processing.overview_matrix import infer_measured_readouts

    rows = [("a", "X", "T1"), ("c", "Y", "T3")]
    measured = infer_measured_readouts(rows, {"a": [1], "c": [3]}, {1, 4})
    # Gene 4 has no reported row: every context's readouts. Gene 1 keeps its
    # observed contexts — being listed doesn't widen a reported perturbation.
    assert measured[4] == {"T1", "T3"}
    assert measured[1] == {"T1"}


def test_significant_only_infers_tested_not_significant_cells() -> None:
    conn = _make_db()
    _add_significant_only_screen(conn)
    materialize_overview_matrix(conn, min_groups=1)

    # Reported cells are untouched.
    assert set(_cells(conn, "screen")) == {(1, "T1"), (2, "T1"), (1, "T2"), (3, "T3")}
    # BBB was tested in X, where T2 was measured → inferred n.s. Nothing else:
    # CCC's T3 was measured in Y only, where AAA/BBB have no rows.
    assert _inferred(conn, "screen") == {(2, "T2")}
    # Summary: BBB measured on 2 readouts (1 reported + 1 inferred), 1 significant.
    assert _summary_inferred(conn, "screen") == {
        1: (2, 2, 0),
        2: (1, 2, 1),
        3: (1, 1, 0),
    }


def test_significant_only_without_contexts_is_one_screen() -> None:
    conn = _make_db()
    _add_significant_only_screen(conn, contexts=())
    materialize_overview_matrix(conn, min_groups=1)
    assert _inferred(conn, "screen") == {
        (1, "T3"),
        (2, "T2"),
        (2, "T3"),
        (3, "T1"),
        (3, "T2"),
    }


def test_library_only_perturbation_becomes_a_row_with_inferred_cells() -> None:
    conn = _make_db()
    _add_significant_only_screen(conn, tested=["DDD", "NOPE"])
    materialize_overview_matrix(conn, min_groups=1)
    genes = {row[0] for row in conn.execute("SELECT central_gene_id FROM overview_matrix_genes")}
    assert 4 in genes  # DDD: in the library, zero reported rows
    assert {(4, "T1"), (4, "T2"), (4, "T3")} <= _inferred(conn, "screen")
    # Tested on all three readouts, none significant, all inferred; no best value.
    assert _summary_inferred(conn, "screen")[4] == (0, 3, 3)
    best = conn.execute(
        "SELECT best_value FROM overview_matrix_summary_cells "
        "WHERE source_table = 'screen' AND central_gene_id = 4"
    ).fetchone()
    assert best == (0.0,)
    # The weaker assumption is labelled as such; within-screen inference isn't.
    basis = _inferred_basis(conn, "screen")
    assert {basis[(4, t)] for t in ("T1", "T2", "T3")} == {"library"}
    assert basis[(2, "T2")] == "screen"
    assert conn.execute(
        "SELECT central_gene_id, inferred_basis FROM overview_matrix_summary_cells "
        "WHERE source_table = 'screen' AND n_inferred > 0 ORDER BY 1"
    ).fetchall() == [(2, "screen"), (4, "library")]


def test_unknown_context_column_skips_inference() -> None:
    conn = _make_db()
    _add_significant_only_screen(conn, contexts=("no_such_column",))
    materialize_overview_matrix(conn, min_groups=1)
    assert _inferred(conn, "screen") == set()


def test_tables_without_significant_only_get_no_inferred_cells(
    conn: sqlite3.Connection,
) -> None:
    materialize_overview_matrix(conn)
    assert conn.execute("SELECT COUNT(*) FROM overview_matrix_inferred_cells").fetchone() == (0,)
