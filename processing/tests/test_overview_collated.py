"""Collated by-readout view of the overview matrix (overview_collated.py).

Hand-built studies over the shared fixture genes (ids 1-4 = AAA..DDD, 9 = a
control). Readout genes are central genes too, so targets are ids 1-4 as well.
"""

import json
import sqlite3

from processing.overview_matrix import materialize_overview_matrix
from test_overview_matrix import _add_link, _make_db, _register

_EXTRA_COLUMNS = (
    "significant_only",
    "gene_species",
    "dataset",
    "effect_column",
    "medium_label",
    "evidence_source",
)


def _with_extra_columns(conn: sqlite3.Connection) -> None:
    for col in _EXTRA_COLUMNS:
        conn.execute(f"ALTER TABLE data_tables ADD COLUMN {col} TEXT")


def _add_study(
    conn: sqlite3.Connection,
    table: str,
    *,
    dataset: str,
    rows: list[tuple[str, int, str, float, float, float]],
    pert_gene: dict[str, int],
    significant_only: dict | None = None,
    label: str | None = None,
    evidence_source: str | None = None,
) -> None:
    """rows: (perturbation, target gene id, context, p, fdr, effect)."""
    conn.execute(
        f"CREATE TABLE {table} (id INTEGER, pert TEXT, target TEXT, ctx TEXT, "
        "p REAL, fdr REAL, lfc REAL)"
    )
    conn.executemany(
        f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (i, pert, f"G{target}", ctx, p, fdr, lfc)
            for i, (pert, target, ctx, p, fdr, lfc) in enumerate(rows, start=1)
        ],
    )
    _add_link(
        conn,
        f"{table}__pert",
        [(pert_gene[r[0]], i) for i, r in enumerate(rows, start=1) if pert_gene.get(r[0])],
    )
    _add_link(conn, f"{table}__target", [(r[1], i) for i, r in enumerate(rows, start=1)])
    _register(
        conn,
        table,
        "perturbation_deg",
        f"target:{table}__target:target,pert:{table}__pert:perturbed",
        pvalue_column="p",
        fdr_column="fdr",
    )
    conn.execute(
        "UPDATE data_tables SET dataset = ?, effect_column = 'lfc', medium_label = ?, "
        "gene_species = 'human', significant_only = ?, evidence_source = ? "
        "WHERE table_name = ?",
        (
            dataset,
            f"{label or dataset} - fixture",
            json.dumps(significant_only) if significant_only else None,
            evidence_source,
            table,
        ),
    )


def _cells(conn: sqlite3.Connection) -> dict[tuple[int, int], tuple[int, int, int, int, int]]:
    return {
        (gene, target): (k, n, up, down, inferred)
        for target, gene, k, n, up, down, inferred in conn.execute(
            "SELECT target_gene_id, central_gene_id, k, n, n_up, n_down, n_inferred "
            "FROM overview_matrix_collated_cells"
        )
    }


def _contrib(conn: sqlite3.Connection, gene: int, target: int):
    return {
        study: (n_tests, significant, inferred_basis)
        for study, n_tests, significant, inferred_basis in conn.execute(
            "SELECT study, n_tests, significant, inferred_basis "
            "FROM overview_matrix_collated_contrib "
            "WHERE central_gene_id = ? AND target_gene_id = ?",
            (gene, target),
        )
    }


PERTS = {"P_AAA": 1, "P_BBB": 2, "P_CCC": 3, "NTC": 9}


def _two_studies() -> sqlite3.Connection:
    conn = _make_db()
    _with_extra_columns(conn)
    # Study A (full table, one context): AAA→T3 significant up, BBB→T3 tested n.s.
    _add_study(
        conn,
        "study_a",
        dataset="ds_a",
        rows=[
            ("P_AAA", 3, "", 1e-6, 0.001, 1.5),
            ("P_BBB", 3, "", 0.4, 0.8, 0.1),
            ("P_AAA", 4, "", 1e-5, 0.01, -0.7),
        ],
        pert_gene=PERTS,
    )
    # Study B: AAA→T3 in three cell types, significant in one (FDR 0.02) → the
    # study counts as significant; a cell-type-specific hit is a hit. BBB→T3
    # significant down.
    _add_study(
        conn,
        "study_b",
        dataset="ds_b",
        rows=[
            ("P_AAA", 3, "c1", 0.001, 0.02, 0.9),
            ("P_AAA", 3, "c2", 0.3, 0.5, 0.2),
            ("P_AAA", 3, "c3", 0.6, 0.9, -0.1),
            ("P_BBB", 3, "", 1e-8, 0.0001, -2.0),
        ],
        pert_gene=PERTS,
    )
    return conn


def test_k_over_n_counts_studies() -> None:
    conn = _two_studies()
    materialize_overview_matrix(conn, min_groups=1)
    cells = _cells(conn)
    # AAA×T3: A significant (up); B significant in c1 (up) → 2 of 2, both up.
    assert cells[(1, 3)] == (2, 2, 2, 0, 0)
    # BBB×T3: A n.s., B significant down → 1 of 2, down.
    assert cells[(2, 3)] == (1, 2, 0, 1, 0)
    # n_tests still records that B tested the pair three times.
    assert _contrib(conn, 1, 3) == {"ds_a": (1, 1, None), "ds_b": (3, 1, None)}


def test_columns_ranked_and_labelled() -> None:
    conn = _two_studies()
    materialize_overview_matrix(conn, min_groups=1)
    columns = conn.execute(
        "SELECT target_gene_id, label, n_convergent, sum_k, sum_n, n_studies "
        "FROM overview_matrix_collated_columns ORDER BY sort_rank"
    ).fetchall()
    # T3 (CCC): AAA's row reaches k = 2 (convergent); 3 significant study-pairs
    # over 4 measurements, 2 studies. T4 (DDD): 1 of 1.
    assert columns == [(3, "CCC", 1, 3, 4, 2), (4, "DDD", 0, 1, 1, 1)]
    group = conn.execute(
        "SELECT label, studies FROM overview_matrix_collated_groups"
    ).fetchone()
    assert group[0] == "RNA response across studies"
    assert [s["study"] for s in json.loads(group[1])] == ["ds_a", "ds_b"]


def test_two_tables_of_one_dataset_count_once() -> None:
    conn = _make_db()
    _with_extra_columns(conn)
    for table in ("half_1", "half_2"):
        _add_study(
            conn,
            table,
            dataset="same_paper",
            rows=[("P_AAA", 3, "", 1e-6, 0.001, 1.0)],
            pert_gene=PERTS,
        )
    materialize_overview_matrix(conn, min_groups=1)
    # One study; it tested the pair twice (once per table).
    assert _cells(conn)[(1, 3)] == (1, 1, 1, 0, 0)
    assert _contrib(conn, 1, 3) == {"same_paper": (2, 1, None)}


def test_one_experiment_in_two_papers_counts_once() -> None:
    conn = _make_db()
    _with_extra_columns(conn)
    for table, dataset in (("paper_1", "ds_1"), ("paper_2", "ds_2")):
        _add_study(
            conn,
            table,
            dataset=dataset,
            rows=[("P_AAA", 3, "", 1e-6, 0.001, 1.0)],
            pert_gene=PERTS,
            evidence_source="same_experiment",
        )
    _add_study(
        conn,
        "other_lab",
        dataset="ds_3",
        rows=[("P_AAA", 3, "", 0.5, 0.9, 0.1)],
        pert_gene=PERTS,
    )
    materialize_overview_matrix(conn, min_groups=1)
    assert _cells(conn)[(1, 3)] == (1, 2, 1, 0, 0)
    assert set(_contrib(conn, 1, 3)) == {"same_experiment", "ds_3"}


def test_controls_are_not_rows() -> None:
    conn = _make_db()
    _with_extra_columns(conn)
    _add_study(
        conn,
        "s",
        dataset="ds",
        rows=[("NTC", 3, "", 1e-9, 1e-6, 1.0), ("P_AAA", 3, "", 1e-6, 0.001, 1.0)],
        pert_gene=PERTS,
    )
    materialize_overview_matrix(conn, min_groups=1)
    assert {gene for gene, _ in _cells(conn)} == {1}


def test_significant_only_study_adds_inferred_measurements() -> None:
    conn = _two_studies()
    # Study C publishes only hits, in two cell types. CCC→T3 hit in X; AAA has a
    # hit in X too (→ T3 measured for AAA, inferred n.s.). DDD is library-only.
    _add_study(
        conn,
        "study_c",
        dataset="ds_c",
        rows=[
            ("P_CCC", 3, "X", 1e-6, 0.001, 1.0),
            ("P_AAA", 4, "X", 1e-6, 0.001, 1.0),
            ("P_BBB", 4, "Y", 1e-6, 0.001, 1.0),
        ],
        pert_gene={**PERTS, "P_DDD": 4},
        significant_only={"context_columns": ["ctx"], "tested_perturbations": ["DDD"]},
    )
    materialize_overview_matrix(conn, min_groups=1)
    cells = _cells(conn)
    # AAA×T3: A sig, B sig, C inferred n.s. → 2 of 3, one inferred.
    assert cells[(1, 3)] == (2, 3, 2, 0, 1)
    assert _contrib(conn, 1, 3)["ds_c"] == (1, 0, "screen")
    # BBB was tested only in Y, where T3 was never a hit → C doesn't count.
    assert "ds_c" not in _contrib(conn, 2, 3)
    # Library-only DDD: measured on T3 (X) and T4 (X, Y) → inferred, basis library.
    assert _contrib(conn, 4, 3) == {"ds_c": (1, 0, "library")}
    assert _contrib(conn, 4, 4) == {"ds_c": (2, 0, "library")}
    # A reported pair's n_tests counts the contexts it was measured in: AAA→T4
    # was reported in X only, and T4 was measured in X and Y — but AAA was only
    # tested in X, so 1.
    assert _contrib(conn, 1, 4)["ds_c"] == (1, 1, None)


def test_phenotype_and_non_rna_tables_are_not_collated() -> None:
    conn = _two_studies()
    conn.execute(
        "UPDATE data_tables SET assay = 'behavior' WHERE table_name = 'study_b'"
    )
    materialize_overview_matrix(conn, min_groups=1)
    studies = json.loads(
        conn.execute("SELECT studies FROM overview_matrix_collated_groups").fetchone()[0]
    )
    assert [s["study"] for s in studies] == ["ds_a"]


def _phenotype_tables(conn: sqlite3.Connection, *, shared_source: str | None) -> None:
    """A wide behavior table and a long one, both mapped to one term."""
    conn.execute("CREATE TABLE beh_wide (id INTEGER, sleepd REAL, sleepn REAL)")
    conn.execute("INSERT INTO beh_wide VALUES (1, -3.0, 0.1), (2, 0.2, 0.1)")
    _add_link(conn, "beh_wide__perturbed", [(1, 1), (2, 2)])
    _register(
        conn,
        "beh_wide",
        "behavior",
        "src:beh_wide__perturbed:perturbed",
        phenotype_columns=["SleepD", "SleepN"],
        metric="signed_neglog_p",
    )
    conn.execute(
        "CREATE TABLE beh_long (id INTEGER, param TEXT, p REAL, fdr REAL, b REAL)"
    )
    conn.execute(
        "INSERT INTO beh_long VALUES (1, 'night sleep', 0.001, 0.9, 1.0), "
        "(2, 'night sleep', 0.001, 0.01, -1.0), (3, 'unmapped', 0.001, 0.01, 1.0)"
    )
    _add_link(conn, "beh_long__perturbed", [(1, 1), (2, 2), (2, 3)])
    _register(
        conn,
        "beh_long",
        "behavior",
        "src:beh_long__perturbed:perturbed",
        pvalue_column="p",
        fdr_column="fdr",
        phenotype_column="param",
    )
    for table, dataset, terms in (
        ("beh_wide", "ds_wide", {"SleepD": "MP:0021198", "SleepN": "MP:0021198"}),
        ("beh_long", "ds_long", {"night sleep": "MP:0021198"}),
    ):
        conn.execute(
            "UPDATE data_tables SET dataset = ?, medium_label = ?, effect_column = 'b', "
            "evidence_source = ?, overview_matrix_phenotype_terms = ? "
            "WHERE table_name = ?",
            (dataset, f"{dataset} - fixture", shared_source, json.dumps(terms), table),
        )


def _with_phenotype_terms(conn: sqlite3.Connection) -> None:
    _with_extra_columns(conn)
    conn.execute(
        "ALTER TABLE data_tables ADD COLUMN overview_matrix_phenotype_terms TEXT"
    )


def test_phenotype_columns_pool_through_terms() -> None:
    conn = _make_db()
    _with_phenotype_terms(conn)
    _phenotype_tables(conn, shared_source=None)
    materialize_overview_matrix(conn, min_groups=1)
    columns = conn.execute(
        "SELECT target_gene_id, label, n_studies FROM overview_matrix_collated_columns "
        "WHERE collate_group = 'phenotype'"
    ).fetchall()
    assert columns == [(-2, "Sleep duration", 2)]
    # AAA: wide p = 0.001 counts; long has an FDR of 0.9, so it doesn't.
    assert _cells(conn)[(1, -2)] == (1, 2, 0, 1, 0)
    # BBB: wide n.s.; long FDR 0.01, effect down.
    assert _cells(conn)[(2, -2)] == (1, 2, 0, 1, 0)
    assert _contrib(conn, 1, -2)["ds_wide"] == (2, 1, None)


def test_phenotype_pooling_counts_a_shared_experiment_once() -> None:
    conn = _make_db()
    _with_phenotype_terms(conn)
    _phenotype_tables(conn, shared_source="one_experiment")
    materialize_overview_matrix(conn, min_groups=1)
    # One study, significant through its wide table.
    assert _cells(conn)[(1, -2)] == (1, 1, 0, 1, 0)
    assert set(_contrib(conn, 1, -2)) == {"one_experiment"}


def test_phenotype_tests_keep_what_a_column_compressed() -> None:
    conn = _make_db()
    _with_phenotype_terms(conn)
    _phenotype_tables(conn, shared_source=None)
    materialize_overview_matrix(conn, min_groups=1)
    rows = conn.execute(
        "SELECT source_label, column_value FROM overview_matrix_phenotype_tests "
        "WHERE target_gene_id = -2 AND central_gene_id = 1 ORDER BY 1, 2"
    ).fetchall()
    assert rows == [
        ("ds_long", "night sleep"),
        ("ds_wide", "SleepD"),
        ("ds_wide", "SleepN"),
    ]


def test_a_study_with_significant_tests_both_ways_is_mixed() -> None:
    conn = _make_db()
    _with_phenotype_terms(conn)
    conn.execute("CREATE TABLE beh (id INTEGER, sleepd REAL, sleepn REAL)")
    conn.execute("INSERT INTO beh VALUES (1, 4.0, -5.0)")
    _add_link(conn, "beh__perturbed", [(1, 1)])
    _register(
        conn,
        "beh",
        "behavior",
        "src:beh__perturbed:perturbed",
        phenotype_columns=["SleepD", "SleepN"],
        metric="signed_neglog_p",
    )
    conn.execute(
        "UPDATE data_tables SET dataset = 'ds', medium_label = 'ds - fixture', "
        "overview_matrix_phenotype_terms = ?",
        (json.dumps({"SleepD": "MP:0021198", "SleepN": "MP:0021198"}),),
    )
    materialize_overview_matrix(conn, min_groups=1)
    # Significant, counted in neither direction, and no single effect to report.
    assert _cells(conn)[(1, -2)] == (1, 1, 0, 0, 0)
    assert conn.execute(
        "SELECT effect FROM overview_matrix_collated_contrib WHERE target_gene_id = -2"
    ).fetchone() == (None,)


def _signs_all(conn: sqlite3.Connection, gene: int, target: int) -> tuple[int, int]:
    return conn.execute(
        "SELECT n_pos_all, n_neg_all FROM overview_matrix_collated_cells "
        "WHERE central_gene_id = ? AND target_gene_id = ?",
        (gene, target),
    ).fetchone()


def test_effect_signs_count_every_measuring_study() -> None:
    conn = _two_studies()
    materialize_overview_matrix(conn, min_groups=1)
    # AAA×T3: A up; B's strongest test (c1) is up → both vote up.
    assert _signs_all(conn, 1, 3) == (2, 0)
    # BBB×T3: A is n.s. but its effect is up; B is significant down. The
    # significant-only view sees one study; over all studies they disagree.
    assert _signs_all(conn, 2, 3) == (1, 1)


def test_inferred_measurements_do_not_vote_on_sign() -> None:
    conn = _two_studies()
    _add_study(
        conn,
        "study_c",
        dataset="ds_c",
        rows=[("P_CCC", 3, "X", 1e-6, 0.001, 1.0), ("P_AAA", 4, "X", 1e-6, 0.001, 1.0)],
        pert_gene=PERTS,
        significant_only={"context_columns": ["ctx"]},
    )
    materialize_overview_matrix(conn, min_groups=1)
    # C's AAA×T3 is inferred (n = 3), but only A and B have a sign.
    assert _cells(conn)[(1, 3)][1] == 3
    assert _signs_all(conn, 1, 3) == (2, 0)


def test_phenotype_signs_count_non_significant_studies() -> None:
    conn = _make_db()
    _with_phenotype_terms(conn)
    _phenotype_tables(conn, shared_source=None)
    materialize_overview_matrix(conn, min_groups=1)
    # AAA: wide significant down; long n.s. with a positive effect.
    assert _signs_all(conn, 1, -2) == (1, 1)
    # BBB: wide n.s., strongest measure positive; long significant down.
    assert _signs_all(conn, 2, -2) == (1, 1)


def test_a_mixed_study_abstains_from_the_sign_count() -> None:
    conn = _make_db()
    _with_phenotype_terms(conn)
    conn.execute("CREATE TABLE beh (id INTEGER, sleepd REAL, sleepn REAL)")
    conn.execute("INSERT INTO beh VALUES (1, 4.0, -5.0)")
    _add_link(conn, "beh__perturbed", [(1, 1)])
    _register(
        conn,
        "beh",
        "behavior",
        "src:beh__perturbed:perturbed",
        phenotype_columns=["SleepD", "SleepN"],
        metric="signed_neglog_p",
    )
    conn.execute(
        "UPDATE data_tables SET dataset = 'ds', medium_label = 'ds - fixture', "
        "overview_matrix_phenotype_terms = ?",
        (json.dumps({"SleepD": "MP:0021198", "SleepN": "MP:0021198"}),),
    )
    materialize_overview_matrix(conn, min_groups=1)
    assert _signs_all(conn, 1, -2) == (0, 0)
