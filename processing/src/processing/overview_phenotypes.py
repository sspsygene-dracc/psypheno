"""Phenotype columns of the by-readout matrix.

Papers name their phenotypes differently, so columns are pooled through ontology
terms: each column of a phenotype table declares one in
``overview_matrix_phenotype_terms``, and every term in `PHENOTYPE_TERMS` is one
by-readout column. uPheno's cross-species MP / ZP terms cover behavior; broad Cell
Ontology classes cover cell proportions. To add a term, look it up in those
ontologies and add it here; config validation rejects anything else.

Same rules as the gene columns (see overview_collated.py): the unit is the study,
which is the `evidence_source` when declared, and a study is significant for a
(gene, term) pair if any of its tests has FDR < 0.05. Most behavior tables publish
only p-values, and with a dozen parameters per term a nominal p would pass by
chance, so their FDR is computed here: Benjamini-Hochberg over each table's tests
of a term. Direction comes from the sign of the study's strongest test.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

COLLATE_GROUP = "phenotype"
GROUP_LABEL = "Phenotypes across studies"
_ALPHA = 0.05

# CURIE -> column label. Behavior: MP / ZP terms as linked by uPheno. Cells: Cell
# Ontology, release 2026-06-08; "%" because the measurement is a change in that
# class's share of cells, not the class itself.
PHENOTYPE_TERMS: dict[str, str] = {
    "MP:0001392": "Locomotor behavior",
    "MP:0021198": "Sleep duration",
    "MP:0011396": "Sleep behavior",
    "ZP:0131183": "Sleep latency",
    "MP:0001486": "Startle reflex",
    "CL:0000617": "% GABAergic neurons",
    "CL:0000679": "% glutamatergic neurons",
    "CL:0000695": "% Cajal-Retzius cells",
    "CL:4023008": "% IT neurons",
    "CL:4023012": "% near-projecting",
    "CL:4023017": "% Sst interneurons",
    "CL:4023038": "% L6b neurons",
    "CL:4023041": "% L5 ET neurons",
    "CL:4023042": "% L6 CT neurons",
}


@dataclass
class PhenotypeSource:
    table_name: str
    study: str
    study_label: str
    base_table: str
    perturbed_link: str
    term_by_column: dict[str, str]  # DB column (wide) or value (long) -> CURIE
    phenotype_column: str | None = None  # set = long
    p_col: str | None = None
    fdr_col: str | None = None
    effect_col: str | None = None
    columns: set[str] = field(default_factory=set)


@dataclass
class _Test:
    p: float
    fdr: float | None  # None until `_fill_fdr`, if the table has none
    effect: float | None
    source_table: str


def _wide_tests(
    conn: sqlite3.Connection, source: PhenotypeSource, src_schema: str, panel: str
) -> list[tuple[int, str, _Test]]:
    """A wide column holds signed −log10(p) already."""
    tests: list[tuple[int, str, _Test]] = []
    for column, term in source.term_by_column.items():
        if column not in source.columns:
            continue
        for gene, raw in conn.execute(
            f"""SELECT lt.central_gene_id, t.{column}
                  FROM {src_schema}.{source.base_table} t
                  JOIN {src_schema}.{source.perturbed_link} lt ON t.id = lt.id
                 WHERE lt.central_gene_id IN (SELECT id FROM {panel})
                   AND t.{column} IS NOT NULL"""
        ):
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            tests.append(
                (gene, term, _Test(10 ** -abs(value), None, value, source.table_name))
            )
    return tests


def _long_tests(
    conn: sqlite3.Connection, source: PhenotypeSource, src_schema: str, panel: str
) -> list[tuple[int, str, _Test]]:
    fdr = f"t.{source.fdr_col}" if source.fdr_col in source.columns else "NULL"
    effect = f"t.{source.effect_col}" if source.effect_col in source.columns else "NULL"
    tests: list[tuple[int, str, _Test]] = []
    for gene, value, raw_p, raw_fdr, raw_effect in conn.execute(
        f"""SELECT lt.central_gene_id, t.{source.phenotype_column}, t.{source.p_col},
                   {fdr}, {effect}
              FROM {src_schema}.{source.base_table} t
              JOIN {src_schema}.{source.perturbed_link} lt ON t.id = lt.id
             WHERE lt.central_gene_id IN (SELECT id FROM {panel})
               AND t.{source.p_col} IS NOT NULL"""
    ):
        term = source.term_by_column.get(str(value))
        if term is None:
            continue
        try:
            tests.append(
                (
                    gene,
                    term,
                    _Test(
                        float(raw_p),
                        None if raw_fdr is None else float(raw_fdr),
                        None if raw_effect is None else float(raw_effect),
                        source.table_name,
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
    return tests


def _fill_fdr(tests: list[_Test]) -> None:
    """Benjamini-Hochberg, in place, over tests from one table and term."""
    ordered = sorted(tests, key=lambda t: t.p)
    smallest = 1.0
    for rank in range(len(ordered), 0, -1):
        test = ordered[rank - 1]
        smallest = min(smallest, test.p * len(ordered) / rank)
        test.fdr = smallest


def materialize_phenotype_collated(
    conn: sqlite3.Connection,
    sources: list[PhenotypeSource],
    src_schema: str,
    panel_table: str,
) -> None:
    """Pool phenotype tables into the collated tables, under `COLLATE_GROUP`.

    The collated tables key columns by an integer, so a term takes a negative id:
    gene ids are positive, and ids stay stable because they follow
    `PHENOTYPE_TERMS` order.
    """
    if not sources:
        return
    by_pair: dict[tuple[str, int, str], list[_Test]] = defaultdict(list)
    # A study can span papers, so it is labelled by all of them.
    label_parts: dict[str, set[str]] = defaultdict(set)
    for source in sources:
        label_parts[source.study].add(source.study_label)
        read = _long_tests if source.phenotype_column else _wide_tests
        without_fdr: dict[str, list[_Test]] = defaultdict(list)
        for gene, term, test in read(conn, source, src_schema, panel_table):
            by_pair[(term, gene, source.study)].append(test)
            if test.fdr is None:
                without_fdr[term].append(test)
        for tests in without_fdr.values():
            _fill_fdr(tests)

    labels = {study: " + ".join(sorted(p)) for study, p in label_parts.items()}
    term_ids = {term: -(i + 1) for i, term in enumerate(PHENOTYPE_TERMS)}
    cells: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    contrib = []
    for (term, gene, study), tests in by_pair.items():
        best = min(tests, key=lambda t: (t.fdr, t.p))
        fdrs = [t.fdr for t in tests]
        significant = min(fdrs) < _ALPHA
        cell = cells[(term, gene)]
        cell[1] += 1
        if significant:
            cell[0] += 1
            if best.effect is not None and best.effect != 0:
                cell[2 if best.effect > 0 else 3] += 1
        contrib.append(
            (
                COLLATE_GROUP,
                term_ids[term],
                gene,
                study,
                labels[study],
                ",".join(sorted({t.source_table for t in tests})),
                len(tests),
                min(fdrs),
                min(t.p for t in tests),
                best.effect,
                int(significant),
                None,
            )
        )
    if not cells:
        return

    conn.executemany(
        "INSERT INTO overview_matrix_collated_cells VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
        [
            (COLLATE_GROUP, term_ids[term], gene, k, n, n_up, n_down)
            for (term, gene), (k, n, n_up, n_down) in cells.items()
        ],
    )
    conn.executemany(
        "INSERT INTO overview_matrix_collated_contrib "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        contrib,
    )

    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for (term, _), (k, n, _, _) in cells.items():
        total = totals[term]
        total[0] += int(k >= 2)
        total[1] += k
        total[2] += n
    studies_by_term: dict[str, set[str]] = defaultdict(set)
    for term, _, study in by_pair:
        studies_by_term[term].add(study)
    ranked = sorted(
        totals, key=lambda t: (-totals[t][0], -totals[t][1], -totals[t][2], t)
    )
    conn.executemany(
        "INSERT INTO overview_matrix_collated_columns VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                COLLATE_GROUP,
                term_ids[term],
                PHENOTYPE_TERMS[term],
                *totals[term],
                len(studies_by_term[term]),
                rank,
            )
            for rank, term in enumerate(ranked)
        ],
    )
    studies = sorted({study for _, _, study in by_pair})
    conn.execute(
        "INSERT INTO overview_matrix_collated_groups VALUES (?, ?, ?, ?)",
        (
            COLLATE_GROUP,
            GROUP_LABEL,
            json.dumps([{"study": s, "label": labels[s]} for s in studies]),
            len(ranked),
        ),
    )
