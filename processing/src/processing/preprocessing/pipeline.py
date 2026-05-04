"""Composable preprocessing pipeline + provenance tracker.

Per-dataset `preprocess.py` scripts compose a `Pipeline` of `Step`s that
read a raw input, clean it, and write the result. Every step records an
`ActionRecord` on a shared `Tracker`; at the end the wrangler calls
`tracker.write(<dataset>/preprocessing.yaml)` to persist the provenance.

Typical use:

    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()
    (
        Pipeline("Supp_1_all_cleaned.csv", tracker=tracker,
                 normalizer=normalizer)
        .read_csv("Supp_1_all.csv")
        .clean_gene("target_gene", species="human",
                    excel_demangle=True, strip_make_unique=True,
                    manual_aliases=MANUAL_ALIASES_HUMAN)
        .write_csv("Supp_1_all_cleaned.csv")
        .run()
    )
    tracker.write(Path("preprocessing.yaml"))

One `Tracker` per dataset; one `Pipeline` per output table; multiple
pipelines may share a tracker. See `processing/preprocessing/steps.py`
for the built-in step types.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from processing.preprocessing.ensembl_index import EnsemblToSymbolMapper
from processing.preprocessing.symbol_index import GeneSymbolNormalizer


# Superset of manual aliases used across human datasets. Wranglers import
# this and (optionally) merge their own per-dataset additions on top.
MANUAL_ALIASES_HUMAN: dict[str, str] = {
    "NOV": "CCN3",
    "MUM1": "PWWP3A",
    "QARS": "QARS1",
    "SARS": "SARS1",
    "TAZ": "TAFAZZIN",
}


@dataclass
class ActionRecord:
    """One entry in the preprocessing provenance log."""

    step: str
    table: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tracker:
    """Collects ActionRecords across all pipelines for a dataset."""

    inputs: list[str] = field(default_factory=list)
    actions: list[ActionRecord] = field(default_factory=list)

    def record(self, step: str, *, table: str | None = None, **summary: Any) -> None:
        self.actions.append(ActionRecord(step=step, table=table, summary=summary))

    def note_input(self, path: str) -> None:
        if path not in self.inputs:
            self.inputs.append(path)

    def to_yaml_dict(self) -> dict[str, Any]:
        """Render the tracker state as the dict that gets dumped to YAML.

        Actions are grouped by `table`; actions without a table land under
        the special key `"_dataset"`.
        """
        tables: dict[str, list[dict[str, Any]]] = {}
        for rec in self.actions:
            entry: dict[str, Any] = {"step": rec.step}
            entry.update(rec.summary)
            key = rec.table or "_dataset"
            tables.setdefault(key, []).append(entry)
        out: dict[str, Any] = {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if self.inputs:
            out["inputs"] = list(self.inputs)
        if tables:
            out["tables"] = tables
        return out

    def write(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                self.to_yaml_dict(),
                f,
                sort_keys=False,
                allow_unicode=True,
                width=100,
            )


@dataclass
class Context:
    """Per-pipeline execution context handed to each Step.apply()."""

    tracker: Tracker
    table: str | None
    normalizer: GeneSymbolNormalizer | None
    ensembl_mapper: EnsemblToSymbolMapper | None


class Pipeline:
    """A chain of `Step`s that produces one output table.

    Construct one Pipeline per output file. Multiple pipelines for the
    same dataset can share a Tracker; their actions all land in the same
    `preprocessing.yaml`.
    """

    def __init__(
        self,
        name: str,
        *,
        tracker: Tracker,
        normalizer: GeneSymbolNormalizer | None = None,
        ensembl_mapper: EnsemblToSymbolMapper | None = None,
    ) -> None:
        self.name = name
        self.tracker = tracker
        self.normalizer = normalizer
        self.ensembl_mapper = ensembl_mapper
        self.steps: list[Step] = []

    def add(self, step: "Step") -> "Pipeline":
        self.steps.append(step)
        return self

    # --- Builder methods (defined in steps.py via monkey-patch at import
    # time would be fragile; instead, the builder methods import their
    # Step classes lazily inside each method to avoid circular imports). ---

    def read_csv(
        self,
        path: str | Path,
        *,
        sep: str = ",",
        dtype: Any = str,
        **kw: Any,
    ) -> "Pipeline":
        from processing.preprocessing.steps import ReadCsv

        return self.add(ReadCsv(path=Path(path), sep=sep, dtype=dtype, read_kw=kw))

    def read_tsv(
        self, path: str | Path, *, dtype: Any = str, **kw: Any
    ) -> "Pipeline":
        return self.read_csv(path, sep="\t", dtype=dtype, **kw)

    def clean_gene(
        self,
        column: str,
        *,
        species: str,
        **flags: Any,
    ) -> "Pipeline":
        from processing.preprocessing.steps import CleanGeneColumnStep

        return self.add(
            CleanGeneColumnStep(column=column, species=species, flags=dict(flags))
        )

    def dropna(self, columns: str | list[str]) -> "Pipeline":
        from processing.preprocessing.steps import DropNa

        if isinstance(columns, str):
            columns = [columns]
        return self.add(DropNa(columns=list(columns)))

    def filter_rows(
        self,
        predicate: Any,
        *,
        description: str,
    ) -> "Pipeline":
        from processing.preprocessing.steps import FilterRows

        return self.add(FilterRows(predicate=predicate, description=description))

    def rename(self, mapping: dict[str, str]) -> "Pipeline":
        from processing.preprocessing.steps import Rename

        return self.add(Rename(mapping=dict(mapping)))

    def reorder(self, columns: list[str]) -> "Pipeline":
        from processing.preprocessing.steps import Reorder

        return self.add(Reorder(columns=list(columns)))

    def drop_columns(
        self,
        columns: str | list[str],
        *,
        errors: str = "raise",
    ) -> "Pipeline":
        from processing.preprocessing.steps import DropColumns

        if isinstance(columns, str):
            columns = [columns]
        return self.add(DropColumns(columns=list(columns), errors=errors))

    def transform_column(
        self,
        column: str,
        func: Any,
        *,
        description: str,
    ) -> "Pipeline":
        from processing.preprocessing.steps import TransformColumn

        return self.add(
            TransformColumn(column=column, func=func, description=description)
        )

    def insert_column(
        self,
        name: str,
        value: Any,
        *,
        position: int | None = None,
    ) -> "Pipeline":
        from processing.preprocessing.steps import InsertColumn

        return self.add(InsertColumn(column=name, value=value, position=position))

    def write_csv(self, path: str | Path, *, sep: str = ",") -> "Pipeline":
        from processing.preprocessing.steps import WriteCsv

        return self.add(WriteCsv(path=Path(path), sep=sep))

    def write_tsv(self, path: str | Path) -> "Pipeline":
        return self.write_csv(path, sep="\t")

    def run(self) -> pd.DataFrame:
        ctx = Context(
            tracker=self.tracker,
            table=self.name,
            normalizer=self.normalizer,
            ensembl_mapper=self.ensembl_mapper,
        )
        df: pd.DataFrame | None = None
        for step in self.steps:
            df = step.apply(df, ctx)
        if df is None:
            raise ValueError(
                f"Pipeline {self.name!r} ended without a DataFrame — did you "
                "forget a read_*/write_* step?"
            )
        return df


def copy_file(src: str | Path, dst: str | Path, *, tracker: Tracker) -> None:
    """Pass-through copy of a companion file, recorded in the tracker.

    Used for files that need to ship to load-db unchanged (e.g. a patient
    list that's referenced from another table). The `dst` filename is the
    table key in the provenance YAML.
    """
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    tracker.note_input(src.name)
    tracker.record("copy_file", table=dst.name, source=src.name)


# Lazy import — Step is defined in steps.py but typed here for the
# Pipeline.add() signature.
from processing.preprocessing.steps import Step  # noqa: E402
