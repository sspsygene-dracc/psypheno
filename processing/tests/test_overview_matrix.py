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
    "expand_in_overview_matrix INTEGER NOT NULL DEFAULT 0, short_label TEXT, "
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
    expand: int = 1,
    phenotype_column: str | None = None,
    phenotype_columns: list[str] | None = None,
    metric: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO data_tables (table_name, assay, pvalue_column, fdr_column, "
        "link_tables, include_in_overview_matrix, expand_in_overview_matrix, "
        "short_label, overview_matrix_phenotype_column, "
        "overview_matrix_phenotype_columns, overview_matrix_metric) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
        (
            table_name,
            assay,
            pvalue_column,
            fdr_column,
            link_tables,
            expand,
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
    assert info["schema_version"] == "3"
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
