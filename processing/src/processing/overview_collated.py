"""Collated by-readout view of the overview matrix.

The expanded matrix groups its columns by study: each source table fans out
into its own block of target-gene columns. This view collapses those blocks:
one column per **readout gene** (joined on `central_gene` id, so a mouse and a
human readout of the same gene meet in one column), and each cell answers

    across the studies that measured this (perturbed gene, readout) pair,
    how many found a significant effect?

as k/n, plus how many of the k went up vs. down.

Counting rules (deliberately simple defaults; revisit on concrete feedback):

- **The unit is the study** — one experiment, not one paper: the table's
  ``evidence_source`` if it declares one, else its dataset directory. Two tables
  from one paper count once, and so does one experiment published twice.
- **A study is significant for a pair if any of its tests is**: ``min(FDR) <
  0.05`` over the cell types / conditions / methods it tested the pair in. A
  cell-type-specific hit is a real finding and must count; the price is that a
  study testing many contexts gets more chances. ``n_tests`` (how often the study
  tested the pair) is kept and shown in the click-through so readers can weigh
  that.
- **Direction** is the sign of the effect on the study's most significant row
  for the pair, counted only for significant studies.
- **Significant-only sources** (`significant_only` in config) contribute their
  inferred tested-not-significant pairs to n, with ``n_tests`` = the number of
  contexts where the pair was measured (see `infer_measured_readouts`).

Only RNA readouts are collated for now (`COLLATE_GROUPS`): Perturb-seq,
perturb-FISH and the expression tables all measure a readout gene's RNA.
Phenotype columns have no shared vocabulary across studies yet, and protein
interactions come from a single study, so collating them adds nothing.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

import click

from processing.combined_pvalues.collection import parse_link_tables_for_direction
from processing.sql_utils import sanitize_identifier

# Modality key → collate group. Modalities not listed aren't collated.
COLLATE_GROUPS = {
    "expression": "rna",
    "perturb_seq": "rna",
    "perturb_fish": "rna",
}
COLLATE_GROUP_LABELS = {"rna": "RNA response across studies"}

# Readout columns materialized per collate group (the UI offers up to this).
COLLATED_TOP_M = 500

SIG_ALPHA = 0.05

COLLATED_TABLES = (
    "overview_matrix_collated_groups",
    "overview_matrix_collated_columns",
    "overview_matrix_collated_cells",
    "overview_matrix_collated_contrib",
)


@dataclass(frozen=True)
class CollateSource:
    """One gene-target source table feeding the collated view."""

    collate_group: str
    table_name: str
    study: str
    study_label: str
    base_table: str
    group_column: str
    perturbed_link: str
    target_link: str
    p_col: str
    fdr_col: str
    effect_col: str | None
    context_columns: list[str] | None  # None = not significant-only
    library_gene_ids: frozenset[int] = frozenset()


def create_collated_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE overview_matrix_collated_groups (
        collate_group TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        studies TEXT NOT NULL,
        n_columns_total INTEGER NOT NULL)"""
    )
    conn.execute(
        """CREATE TABLE overview_matrix_collated_columns (
        collate_group TEXT NOT NULL,
        target_gene_id INTEGER NOT NULL,
        label TEXT NOT NULL,
        n_convergent INTEGER NOT NULL,
        sum_k INTEGER NOT NULL,
        sum_n INTEGER NOT NULL,
        n_studies INTEGER NOT NULL,
        sort_rank INTEGER NOT NULL,
        PRIMARY KEY (collate_group, target_gene_id)) WITHOUT ROWID"""
    )
    # Column-major like the expanded cells: the read path fetches every gene's
    # cell for a set of columns.
    conn.execute(
        """CREATE TABLE overview_matrix_collated_cells (
        collate_group TEXT NOT NULL,
        target_gene_id INTEGER NOT NULL,
        central_gene_id INTEGER NOT NULL,
        k INTEGER NOT NULL,
        n INTEGER NOT NULL,
        n_up INTEGER NOT NULL,
        n_down INTEGER NOT NULL,
        n_inferred INTEGER NOT NULL,
        PRIMARY KEY (collate_group, target_gene_id, central_gene_id)) WITHOUT ROWID"""
    )
    # One row per study behind a cell, for the click-through. `inferred_basis`
    # is set when the study never reported the pair (significant-only source).
    conn.execute(
        """CREATE TABLE overview_matrix_collated_contrib (
        collate_group TEXT NOT NULL,
        target_gene_id INTEGER NOT NULL,
        central_gene_id INTEGER NOT NULL,
        study TEXT NOT NULL,
        study_label TEXT NOT NULL,
        source_tables TEXT NOT NULL,
        n_tests INTEGER NOT NULL,
        min_fdr REAL,
        best_p REAL,
        effect REAL,
        significant INTEGER NOT NULL,
        inferred_basis TEXT,
        PRIMARY KEY (collate_group, target_gene_id, central_gene_id, study))
        WITHOUT ROWID"""
    )


def _create_temp_tables(conn: sqlite3.Connection) -> None:
    for name in ("collate_tests", "collate_pairs", "collate_group_gene", "collate_target"):
        conn.execute(f"DROP TABLE IF EXISTS temp.{name}")
    # Untyped `grp`: compared against the source column with its own type.
    conn.execute("CREATE TEMP TABLE collate_group_gene (grp, gene INTEGER NOT NULL)")
    conn.execute("CREATE TEMP TABLE collate_target (id INTEGER NOT NULL, target INTEGER NOT NULL)")
    conn.execute(
        """CREATE TEMP TABLE collate_tests (
        source_table TEXT NOT NULL, gene INTEGER NOT NULL, target INTEGER NOT NULL,
        ctx TEXT NOT NULL, p REAL, fdr REAL, effect REAL)"""
    )
    conn.execute(
        """CREATE TEMP TABLE collate_pairs (
        collate_group TEXT NOT NULL, study TEXT NOT NULL, study_label TEXT NOT NULL,
        source_table TEXT NOT NULL, gene INTEGER NOT NULL, target INTEGER NOT NULL,
        n_rows INTEGER NOT NULL, n_ctx INTEGER NOT NULL,
        min_fdr REAL, best_p REAL, effect REAL, inferred_basis TEXT)"""
    )


def _load_source_tests(
    conn: sqlite3.Connection,
    source: CollateSource,
    group_genes: dict[object, list[int]],
    context_expr: str,
    src_schema: str,
) -> None:
    """Reported rows of one table → temp.collate_tests (panel genes only)."""
    conn.execute("DELETE FROM temp.collate_group_gene")
    conn.executemany(
        "INSERT INTO temp.collate_group_gene (grp, gene) VALUES (?, ?)",
        [(grp, gene) for grp, genes in group_genes.items() for gene in genes],
    )
    conn.execute("DELETE FROM temp.collate_target")
    conn.execute(
        f"INSERT INTO temp.collate_target (id, target) "
        f"SELECT id, central_gene_id FROM {src_schema}.{source.target_link}"
    )
    conn.execute("DROP INDEX IF EXISTS temp.collate_target_id_idx")
    conn.execute("CREATE INDEX temp.collate_target_id_idx ON collate_target (id)")
    conn.execute("DROP INDEX IF EXISTS temp.collate_group_gene_idx")
    conn.execute("CREATE INDEX temp.collate_group_gene_idx ON collate_group_gene (grp)")
    effect = f"t.{source.effect_col}" if source.effect_col else "NULL"
    conn.execute(
        f"""INSERT INTO temp.collate_tests
                (source_table, gene, target, ctx, p, fdr, effect)
            SELECT ?, gg.gene, ct.target, {context_expr}, t.{source.p_col},
                   t.{source.fdr_col}, {effect}
              FROM {src_schema}.{source.base_table} t
              JOIN temp.collate_group_gene gg ON gg.grp = t.{source.group_column}
              JOIN temp.collate_target ct ON ct.id = t.id""",
        (source.table_name,),
    )


def _write_source_pairs(conn: sqlite3.Connection, source: CollateSource) -> None:
    """Collapse one table's tests to per-(gene, target) pairs, then add the
    inferred pairs of a significant-only table."""
    conn.execute(
        """INSERT INTO temp.collate_pairs
               (collate_group, study, study_label, source_table, gene, target,
                n_rows, n_ctx, min_fdr, best_p, effect, inferred_basis)
           SELECT ?, ?, ?, ?, a.gene, a.target, a.n_rows, a.n_ctx, a.min_fdr,
                  b.best_p, b.effect, NULL
             FROM (SELECT gene, target, COUNT(*) AS n_rows,
                          COUNT(DISTINCT ctx) AS n_ctx, MIN(fdr) AS min_fdr
                     FROM temp.collate_tests WHERE source_table = ?
                    GROUP BY gene, target) a
             -- SQLite: with a single MIN() aggregate, the bare `effect` comes
             -- from the row holding that minimum, i.e. the best row.
             JOIN (SELECT gene, target, MIN(COALESCE(p, fdr)) AS best_p, effect
                     FROM temp.collate_tests WHERE source_table = ?
                    GROUP BY gene, target) b
               ON b.gene = a.gene AND b.target = a.target""",
        (
            source.collate_group,
            source.study,
            source.study_label,
            source.table_name,
            source.table_name,
            source.table_name,
        ),
    )
    if source.context_columns is None:
        return

    # Significant-only: a pair is measured in every context where the gene was
    # tested (has a reported row there, or is a library-only gene → every
    # context) and the readout was reported for someone. Mirrors
    # overview_matrix.infer_measured_readouts, at central-gene level.
    conn.execute("DROP TABLE IF EXISTS temp.collate_gene_ctx")
    conn.execute(
        """CREATE TEMP TABLE collate_gene_ctx AS
           SELECT DISTINCT gene, ctx, 'screen' AS basis
             FROM temp.collate_tests WHERE source_table = ?""",
        (source.table_name,),
    )
    reported_genes = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT gene FROM temp.collate_gene_ctx"
        )
    }
    contexts = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT ctx FROM temp.collate_tests WHERE source_table = ?",
            (source.table_name,),
        )
    ]
    conn.executemany(
        "INSERT INTO temp.collate_gene_ctx (gene, ctx, basis) VALUES (?, ?, 'library')",
        [
            (gene, ctx)
            for gene in sorted(source.library_gene_ids - reported_genes)
            for ctx in contexts
        ],
    )
    conn.execute(
        """CREATE INDEX temp.collate_gene_ctx_idx ON collate_gene_ctx (ctx)"""
    )
    conn.execute("DROP TABLE IF EXISTS temp.collate_measured")
    conn.execute(
        """CREATE TEMP TABLE collate_measured AS
           SELECT gc.gene, ctt.target, COUNT(*) AS n_ctx, MIN(gc.basis) AS basis
             FROM temp.collate_gene_ctx gc
             JOIN (SELECT DISTINCT ctx, target FROM temp.collate_tests
                    WHERE source_table = ?) ctt ON ctt.ctx = gc.ctx
            GROUP BY gc.gene, ctt.target""",
        (source.table_name,),
    )
    conn.execute(
        "CREATE INDEX temp.collate_measured_idx ON collate_measured (gene, target)"
    )
    # Reported pairs: n_ctx becomes the contexts the pair was *measured* in.
    conn.execute(
        """UPDATE temp.collate_pairs
              SET n_ctx = MAX(n_ctx, (SELECT m.n_ctx FROM temp.collate_measured m
                                       WHERE m.gene = collate_pairs.gene
                                         AND m.target = collate_pairs.target))
            WHERE source_table = ?
              AND EXISTS (SELECT 1 FROM temp.collate_measured m
                           WHERE m.gene = collate_pairs.gene
                             AND m.target = collate_pairs.target)""",
        (source.table_name,),
    )
    # Inferred pairs: measured, never reported.
    conn.execute(
        """INSERT INTO temp.collate_pairs
               (collate_group, study, study_label, source_table, gene, target,
                n_rows, n_ctx, min_fdr, best_p, effect, inferred_basis)
           SELECT ?, ?, ?, ?, m.gene, m.target, 0, m.n_ctx, NULL, NULL, NULL,
                  -- 'library' < 'screen', so MIN() above means "any library
                  -- context"; a gene is either all-library or all-screen anyway.
                  m.basis
             FROM temp.collate_measured m
            WHERE NOT EXISTS (SELECT 1 FROM temp.collate_tests t
                               WHERE t.source_table = ?
                                 AND t.gene = m.gene AND t.target = m.target)""",
        (
            source.collate_group,
            source.study,
            source.study_label,
            source.table_name,
            source.table_name,
        ),
    )
    for name in ("collate_gene_ctx", "collate_measured"):
        conn.execute(f"DROP TABLE IF EXISTS temp.{name}")


def materialize_collated(
    conn: sqlite3.Connection,
    sources: list[CollateSource],
    group_genes_by_table: dict[str, dict[object, list[int]]],
    context_exprs: dict[str, str],
    src_schema: str,
) -> None:
    """Build the overview_matrix_collated_* tables from the gene-axis sources."""
    if not sources:
        return
    _create_temp_tables(conn)
    conn.execute(
        "CREATE INDEX temp.collate_tests_idx ON collate_tests "
        "(source_table, gene, target)"
    )
    for source in sources:
        _load_source_tests(
            conn,
            source,
            group_genes_by_table[source.table_name],
            context_exprs[source.table_name],
            src_schema,
        )
        _write_source_pairs(conn, source)

    # Study level: collapse a study's tables; n_tests = how often the study
    # tested the pair. Significant = any test passed (min FDR < alpha).
    conn.execute("DROP TABLE IF EXISTS temp.collate_study_pairs")
    conn.execute(
        f"""CREATE TEMP TABLE collate_study_pairs AS
            SELECT a.collate_group, a.study, a.study_label, a.gene, a.target,
                   a.source_tables, a.n_tests, a.min_fdr, b.best_p, b.effect,
                   a.inferred_basis,
                   CASE WHEN a.min_fdr IS NOT NULL AND a.min_fdr < {SIG_ALPHA}
                        THEN 1 ELSE 0 END AS significant
              FROM (SELECT collate_group, study, MIN(study_label) AS study_label,
                           gene, target,
                           GROUP_CONCAT(DISTINCT source_table) AS source_tables,
                           SUM(MAX(n_rows, n_ctx)) AS n_tests,
                           MIN(min_fdr) AS min_fdr,
                           -- inferred only if no table of the study reported it
                           CASE WHEN SUM(n_rows) = 0 THEN MIN(inferred_basis) END
                             AS inferred_basis
                      FROM temp.collate_pairs
                     GROUP BY collate_group, study, gene, target) a
              LEFT JOIN (SELECT collate_group, study, gene, target,
                                MIN(best_p) AS best_p, effect
                           FROM temp.collate_pairs WHERE best_p IS NOT NULL
                          GROUP BY collate_group, study, gene, target) b
                ON b.collate_group = a.collate_group AND b.study = a.study
               AND b.gene = a.gene AND b.target = a.target"""
    )
    conn.execute(
        "CREATE INDEX temp.collate_study_pairs_idx ON collate_study_pairs "
        "(collate_group, target, gene)"
    )
    conn.execute("DROP TABLE IF EXISTS temp.collate_cells")
    conn.execute(
        """CREATE TEMP TABLE collate_cells AS
           SELECT collate_group, target, gene,
                  SUM(significant) AS k, COUNT(*) AS n,
                  SUM(significant AND effect > 0) AS n_up,
                  SUM(significant AND effect < 0) AS n_down,
                  SUM(inferred_basis IS NOT NULL) AS n_inferred
             FROM temp.collate_study_pairs
            GROUP BY collate_group, target, gene"""
    )

    groups = sorted({s.collate_group for s in sources})
    for group in groups:
        ranked = conn.execute(
            """SELECT target, SUM(k >= 2) AS n_conv, SUM(k) AS sum_k,
                      SUM(n) AS sum_n
                 FROM temp.collate_cells WHERE collate_group = ?
                GROUP BY target HAVING SUM(k) >= 1
                ORDER BY n_conv DESC, sum_k DESC, sum_n DESC, target ASC
                LIMIT ?""",
            (group, COLLATED_TOP_M),
        ).fetchall()
        n_studies = dict(
            conn.execute(
                """SELECT target, COUNT(DISTINCT study) FROM temp.collate_study_pairs
                    WHERE collate_group = ? GROUP BY target""",
                (group,),
            ).fetchall()
        )
        labels = dict(
            conn.execute(
                f"SELECT id, human_symbol FROM {src_schema}.central_gene "
                f"WHERE id IN ({','.join('?' for _ in ranked)})",
                [r[0] for r in ranked],
            ).fetchall()
        ) if ranked else {}
        conn.executemany(
            "INSERT INTO overview_matrix_collated_columns "
            "(collate_group, target_gene_id, label, n_convergent, sum_k, sum_n, "
            " n_studies, sort_rank) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    group,
                    target,
                    labels.get(target) or f"#{target}",
                    n_conv,
                    sum_k,
                    sum_n,
                    n_studies.get(target, 0),
                    rank,
                )
                for rank, (target, n_conv, sum_k, sum_n) in enumerate(ranked)
            ],
        )
        conn.execute(
            """INSERT INTO overview_matrix_collated_cells
                   (collate_group, target_gene_id, central_gene_id, k, n, n_up,
                    n_down, n_inferred)
               SELECT c.collate_group, c.target, c.gene, c.k, c.n, c.n_up,
                      c.n_down, c.n_inferred
                 FROM temp.collate_cells c
                 JOIN overview_matrix_collated_columns k
                   ON k.collate_group = c.collate_group
                  AND k.target_gene_id = c.target
                WHERE c.collate_group = ?""",
            (group,),
        )
        conn.execute(
            """INSERT INTO overview_matrix_collated_contrib
                   (collate_group, target_gene_id, central_gene_id, study,
                    study_label, source_tables, n_tests, min_fdr, best_p, effect,
                    significant, inferred_basis)
               SELECT s.collate_group, s.target, s.gene, s.study, s.study_label,
                      s.source_tables, s.n_tests, s.min_fdr, s.best_p, s.effect,
                      s.significant, s.inferred_basis
                 FROM temp.collate_study_pairs s
                 JOIN overview_matrix_collated_columns k
                   ON k.collate_group = s.collate_group
                  AND k.target_gene_id = s.target
                WHERE s.collate_group = ?""",
            (group,),
        )
        studies = sorted(
            {(s.study, s.study_label) for s in sources if s.collate_group == group}
        )
        conn.execute(
            "INSERT INTO overview_matrix_collated_groups "
            "(collate_group, label, studies, n_columns_total) VALUES (?, ?, ?, ?)",
            (
                group,
                COLLATE_GROUP_LABELS.get(group, group),
                json.dumps([{"study": s, "label": label} for s, label in studies]),
                len(ranked),
            ),
        )
        (n_cells,) = conn.execute(
            "SELECT COUNT(*) FROM overview_matrix_collated_cells WHERE collate_group = ?",
            (group,),
        ).fetchone()
        click.echo(
            f"  Overview matrix: collated '{group}' → {len(ranked)} readout columns / "
            f"{n_cells} cells over {len(studies)} studies"
        )

    for name in (
        "collate_tests",
        "collate_pairs",
        "collate_group_gene",
        "collate_target",
        "collate_study_pairs",
        "collate_cells",
    ):
        conn.execute(f"DROP TABLE IF EXISTS temp.{name}")


def target_link_for(link_tables_raw: str | None) -> str | None:
    links = parse_link_tables_for_direction(link_tables_raw or "", "target")
    if not links:
        return None
    try:
        return sanitize_identifier(links[0])
    except ValueError:
        return None
