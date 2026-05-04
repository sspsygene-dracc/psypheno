"""Top-level orchestration for the combined-p-values pipeline.

`MetaAnalysisRun.run()` wires the seven stages together:
  1. load source-table catalog
  2. load gene-flag reference data (`GeneFlagger`)
  3. enumerate `ComputeGroup` specs (`ComputeGroupBuilder`)
  4. master scan: collect p-values per direction once
  5. derive each group's `CollectedPvalues` by filtering, applying min_tables
  6. submit non-empty groups to a thread pool calling `call_r_combine`
  7. create per-group output tables + the `combined_pvalue_groups` index

`compute_combined_pvalues` is a thin wrapper kept for backwards compatibility
with `sq_load.py` and the test suite.
"""

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import click

from . import r_runner
from .collection import collect_pvalues_for_tables, filter_collected
from .data import (
    CollectedGroup,
    CollectedPvalues,
    ComputeGroup,
    GeneCombinedPvalues,
    Regulation,
    RJobInput,
    SourceTableQuad,
    SourceTableRow,
)
from .flags import GeneFlagger
from .groups import ComputeGroupBuilder
from .writer import write_combined_results


# Master scans are keyed by (direction, regulation) — 2 directions × 3
# regulations = 6 scans, each producing one CollectedPvalues that derived
# groups filter down from.
MasterKey = tuple[str, Regulation]


class MetaAnalysisRun:
    """One end-to-end run of the combined-p-values pipeline.

    Stages, each its own private method:
      1. `_load_source_tables` — query data_tables for tables with a
         pvalue_column.
      2. `_load_gene_flagger` — load HGNC / TF / NIMH reference data.
      3. `_build_compute_groups` — enumerate the global / assay / disease /
         organism / pairwise / 3-way ComputeGroup specs per direction.
      4. `_collect_master_pvalues` — two SQLite scans (one per direction)
         producing master CollectedPvalues that all groups derive from.
      5. `_derive_collected_groups` — filter the masters down to each group's
         table subset, dropping groups below their `min_tables` threshold.
      6. `_run_r_jobs` — submit non-empty groups to a thread pool, each
         calling `call_r_combine`.
      7. `_write_all_results` — create per-group output tables and the
         `combined_pvalue_groups` index.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        hgnc_path: Path | None = None,
        no_index: bool = False,
        nimh_csv_path: Path | None = None,
        tf_list_path: Path | None = None,
    ):
        self.conn = conn
        self.hgnc_path = hgnc_path
        self.no_index = no_index
        self.nimh_csv_path = nimh_csv_path
        self.tf_list_path = tf_list_path

    # -- top-level pipeline --------------------------------------------------

    def run(self) -> None:
        click.echo("\nComputing combined p-values...")

        source_tables = self._load_source_tables()
        if not source_tables:
            click.echo("  No tables with pvalue_column configured, skipping.")
            return

        flagger = self._load_gene_flagger()
        click.echo(f"  Found {len(source_tables)} tables with p-value columns")

        groups = self._build_compute_groups(source_tables)

        tables_4col: list[SourceTableQuad] = [
            (t[0], t[1], t[2], t[6]) for t in source_tables
        ]
        masters = self._collect_master_pvalues(tables_4col)

        collected = self._derive_collected_groups(groups, masters, tables_4col)

        r_results_by_idx = self._run_r_jobs(collected)

        self._write_all_results(collected, r_results_by_idx, flagger)

    # -- stages --------------------------------------------------------------

    def _load_source_tables(self) -> list[SourceTableRow]:
        return self.conn.execute(
            "SELECT table_name, pvalue_column, link_tables, assay, disease, "
            "organism_key, effect_column FROM data_tables "
            "WHERE pvalue_column IS NOT NULL"
        ).fetchall()

    def _load_gene_flagger(self) -> GeneFlagger:
        return GeneFlagger.from_db(
            self.conn,
            hgnc_path=self.hgnc_path,
            nimh_csv_path=self.nimh_csv_path,
            tf_list_path=self.tf_list_path,
        )

    def _build_compute_groups(
        self, source_tables: list[SourceTableRow]
    ) -> list[ComputeGroup]:
        return ComputeGroupBuilder(source_tables).build()

    def _collect_master_pvalues(
        self, tables_4col: list[SourceTableQuad]
    ) -> dict[MasterKey, CollectedPvalues]:
        """Collect master p-value sets, one per (direction × regulation).

        Six scans total: target/perturbed × any/up/down. Each filtered group
        downstream is derived from its matching master via `filter_collected`.
        """
        click.echo(
            "\n  Collecting p-values "
            "(6 master scans by direction × regulation)..."
        )
        masters: dict[MasterKey, CollectedPvalues] = {}
        regulations: tuple[Regulation, ...] = ("any", "up", "down")
        for direction in ("target", "perturbed"):
            for regulation in regulations:
                rlbl = "" if regulation == "any" else f", reg={regulation}"
                masters[(direction, regulation)] = collect_pvalues_for_tables(
                    self.conn,
                    tables_4col,
                    f"[direction={direction}{rlbl}] ",
                    direction=direction,
                    regulation=regulation,
                )
        return masters

    def _derive_collected_groups(
        self,
        groups: list[ComputeGroup],
        masters: dict[MasterKey, CollectedPvalues],
        tables_4col: list[SourceTableQuad],
    ) -> list[CollectedGroup]:
        # `all_table_names` is regulation-specific: tables without an
        # effect_column never appear in up/down masters, so the "use master
        # directly" shortcut needs the regulation-matching set.
        all_names_by_reg: dict[Regulation, set[str]] = {
            "any": {t[0] for t in tables_4col},
            "up": {t[0] for t in tables_4col if t[3]},
            "down": {t[0] for t in tables_4col if t[3]},
        }

        def _candidate_for(group: ComputeGroup) -> CollectedPvalues:
            master = masters[(group.direction, group.regulation)]
            unique = {t[0] for t in group.tables}
            if unique == all_names_by_reg[group.regulation]:
                return master
            return filter_collected(master, unique)

        out: list[CollectedGroup] = []
        for group in groups:
            master = masters[(group.direction, group.regulation)]
            candidate = _candidate_for(group)

            # min_tables must be checked against tables that *actually* contribute
            # in this direction — a filter group may include tables that all lack
            # the requested direction (pure-target tables in a perturbed group, or
            # vice versa), which would otherwise produce an empty R job.
            contributing: set[str] = set()
            for gene_tbls in candidate.per_table.values():
                contributing.update(gene_tbls.keys())

            if len(contributing) < group.min_tables:
                click.echo(
                    f"  {group.label}Skipping — only {len(contributing)} source "
                    f"table(s) contribute in direction={group.direction}"
                    f", regulation={group.regulation}"
                )
                final_pvalues: CollectedPvalues = CollectedPvalues()
            else:
                final_pvalues = candidate
                if candidate is not master:
                    click.echo(
                        f"  {group.label}Derived from "
                        f"direction={group.direction}, "
                        f"regulation={group.regulation} master "
                        f"({len(contributing)} tables)"
                    )

            out.append(CollectedGroup(
                pvalues=final_pvalues,
                out_table=group.out_table,
                label=group.label,
                direction=group.direction,
                regulation=group.regulation,
                assay_filter=group.assay_filter,
                disease_filter=group.disease_filter,
                organism_filter=group.organism_filter,
                use_gene_flags=group.use_gene_flags,
            ))
        return out

    def _run_r_jobs(
        self, collected: list[CollectedGroup]
    ) -> dict[int, dict[int, GeneCombinedPvalues]]:
        # Submit non-empty groups to the thread pool. We dispatch through
        # `r_runner.call_r_combine` (rather than a local import) so test
        # patches at `processing.combined_pvalues.r_runner.call_r_combine`
        # take effect.
        r_jobs: list[RJobInput] = [
            RJobInput(idx=i, pvalues=cg.pvalues, label=cg.label)
            for i, cg in enumerate(collected)
            if not cg.pvalues.is_empty()
        ]
        max_workers = min(len(r_jobs), os.cpu_count() or 4) if r_jobs else 1
        click.echo(
            f"\n  Launching {len(r_jobs)} R meta-analysis job(s) "
            f"with {max_workers} parallel workers..."
        )

        r_results_by_idx: dict[int, dict[int, GeneCombinedPvalues]] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx: dict[Any, tuple[int, str]] = {}
            for job in r_jobs:
                click.echo(f"  {job.label}Submitting R job...")
                future = executor.submit(r_runner.call_r_combine, job.pvalues)
                future_to_idx[future] = (job.idx, job.label)

            for future in as_completed(future_to_idx):
                idx, label = future_to_idx[future]
                try:
                    result = future.result()
                    r_results_by_idx[idx] = result if result is not None else {}
                    click.echo(f"  {label}R job completed.")
                except Exception as e:  # pylint: disable=broad-exception-caught
                    click.echo(click.style(
                        f"  {label}R job failed: {e}", fg="red",
                    ))
                    r_results_by_idx[idx] = {}

        return r_results_by_idx

    def _write_all_results(
        self,
        collected: list[CollectedGroup],
        r_results_by_idx: dict[int, dict[int, GeneCombinedPvalues]],
        flagger: GeneFlagger,
    ) -> None:
        click.echo("\n  Writing results to database...")
        self._ensure_groups_metadata_table()

        for i, cg in enumerate(collected):
            if cg.pvalues.is_empty():
                # Group was skipped (< min_tables source tables)
                self._record_group_metadata(
                    cg, table_name=None,
                    num_source_tables=len(cg.pvalues.per_table),
                )
                continue

            r_results = r_results_by_idx.get(i, {})
            flags_fn = flagger.flags_for if cg.use_gene_flags else None

            write_combined_results(
                self.conn, cg.out_table, cg.pvalues, r_results,
                self.no_index, flags_fn, cg.label,
            )

            num_source = len({
                tbl
                for gene_tbls in cg.pvalues.per_table.values()
                for tbl in gene_tbls
            })
            self._record_group_metadata(
                cg, table_name=cg.out_table, num_source_tables=num_source,
            )

    # -- low-level helpers ---------------------------------------------------

    def _ensure_groups_metadata_table(self) -> None:
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS combined_pvalue_groups (
            assay_filter TEXT,
            disease_filter TEXT,
            organism_filter TEXT,
            direction TEXT,
            regulation TEXT NOT NULL DEFAULT 'any',
            table_name TEXT,
            num_source_tables INTEGER,
            PRIMARY KEY (
                assay_filter, disease_filter, organism_filter,
                direction, regulation
            )
            )"""
        )

    def _record_group_metadata(
        self,
        cg: CollectedGroup,
        *,
        table_name: str | None,
        num_source_tables: int,
    ) -> None:
        self.conn.execute(
            "INSERT INTO combined_pvalue_groups "
            "(assay_filter, disease_filter, organism_filter, direction, "
            "regulation, table_name, num_source_tables) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                cg.assay_filter,
                cg.disease_filter,
                cg.organism_filter,
                cg.direction,
                cg.regulation,
                table_name,
                num_source_tables,
            ),
        )
        self.conn.commit()


def compute_combined_pvalues(
    conn: sqlite3.Connection,
    hgnc_path: Path | None = None,
    no_index: bool = False,
    nimh_csv_path: Path | None = None,
    tf_list_path: Path | None = None,
) -> None:
    """Compute and store combined p-values per gene across all datasets,
    then separately per assay / disease / organism (and their combinations)."""
    MetaAnalysisRun(
        conn,
        hgnc_path=hgnc_path,
        no_index=no_index,
        nimh_csv_path=nimh_csv_path,
        tf_list_path=tf_list_path,
    ).run()
