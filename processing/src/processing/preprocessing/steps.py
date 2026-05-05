"""Built-in `Step` types for the preprocessing pipeline.

Each Step is a small dataclass with an `apply()` method. Steps record
their action on `ctx.tracker` so the resulting `preprocessing.yaml`
captures every change made to the data.

Wranglers can also subclass `Step` directly for one-off transforms; the
escape hatch is `pipeline.add(MyCustomStep(...))`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ClassVar, cast

import pandas as pd

from processing.preprocessing.dataframe import clean_gene_column

if TYPE_CHECKING:
    from processing.preprocessing.pipeline import Context


class Step(ABC):
    """Base class for pipeline steps.

    A Step receives the current DataFrame (or None for read steps) and
    returns the next DataFrame. Steps record their action on
    `ctx.tracker.record(...)`.
    """

    name: ClassVar[str]

    @abstractmethod
    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame | None: ...


def _require_df(df: pd.DataFrame | None, step: str) -> pd.DataFrame:
    if df is None:
        raise ValueError(
            f"Step {step!r} requires a DataFrame; precede it with read_csv/read_tsv."
        )
    return df


@dataclass
class ReadCsv(Step):
    """Read a CSV/TSV into a DataFrame. Sets the pipeline's df."""

    name: ClassVar[str] = "read_csv"

    path: Path
    sep: str = ","
    dtype: Any = str
    read_kw: dict[str, Any] = field(default_factory=dict)

    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame:
        if df is not None:
            raise ValueError(
                f"read_csv({self.path}) called on a pipeline that already has a "
                "DataFrame. Use a fresh Pipeline per output table."
            )
        loaded = pd.read_csv(self.path, sep=self.sep, dtype=self.dtype, **self.read_kw)
        ctx.tracker.note_input(self.path.name)
        ctx.tracker.record(
            self.name,
            table=ctx.table,
            source=self.path.name,
            separator=self.sep,
            rows=len(loaded),
            columns=list(loaded.columns),
        )
        return loaded


@dataclass
class FromDataFrame(Step):
    """Start a pipeline from an already-loaded DataFrame.

    Useful for multi-sheet Excel inputs: the wrangler reads the workbook
    once with `pd.read_excel(sheet_name=None)`, then runs one Pipeline
    per sheet using `from_dataframe(sheet_df)` as the starting step.
    """

    name: ClassVar[str] = "from_dataframe"

    df: pd.DataFrame
    label: str | None = None  # human-readable source label, e.g. "sheet=foo"

    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame:
        if df is not None:
            raise ValueError(
                "from_dataframe called on a pipeline that already has a "
                "DataFrame. Use a fresh Pipeline per starting frame."
            )
        ctx.tracker.record(
            self.name,
            table=ctx.table,
            source=self.label,
            rows=len(self.df),
            columns=list(self.df.columns),
        )
        return self.df.copy()


@dataclass
class CleanGeneColumnStep(Step):
    """Resolve and annotate a gene-name column via `clean_gene_column`.

    Records the per-tag counts plus a small sample of unresolved values
    to the tracker. Keeps `<column>_raw` and `_<column>_resolution` in the
    output by default — wranglers can chain `.drop_columns(...)` to remove
    them, and that drop will be tracked too.
    """

    name: ClassVar[str] = "clean_gene_column"

    column: str
    species: str
    flags: dict[str, Any]
    sample_unresolved_size: int = 10

    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame:
        df = _require_df(df, self.name)
        if ctx.normalizer is None:
            raise ValueError(
                "clean_gene step requires a GeneSymbolNormalizer; pass "
                "normalizer=... to Pipeline()."
            )
        flags = dict(self.flags)
        if flags.get("resolve_via_ensembl_map") and ctx.ensembl_mapper is None:
            raise ValueError(
                "resolve_via_ensembl_map=True requires an EnsemblToSymbolMapper; "
                "pass ensembl_mapper=... to Pipeline()."
            )
        if flags.get("resolve_gencode_clone") and ctx.gencode_clone_index is None:
            raise ValueError(
                "resolve_gencode_clone=True requires a GencodeCloneIndex; "
                "pass gencode_clone_index=... to Pipeline()."
            )
        out, report = clean_gene_column(
            df,
            self.column,
            species=self.species,  # type: ignore[arg-type]
            normalizer=ctx.normalizer,
            ensembl_mapper=ctx.ensembl_mapper,
            gencode_clone_index=ctx.gencode_clone_index,
            **flags,
        )

        # Pull a small sample of unresolved values to make the YAML useful
        # for human inspection without ballooning its size.
        unresolved_mask = [r == "unresolved" for r in report.resolutions]
        unresolved_values: list[str] = []
        for resolved, raw in zip(unresolved_mask, df[self.column].tolist()):
            if resolved and raw not in ("", None) and not isinstance(raw, float):
                unresolved_values.append(str(raw))
                if len(unresolved_values) >= self.sample_unresolved_size:
                    break

        # Serialize flags as plain JSON-compatible types (drop callables /
        # objects). Manual aliases are explicitly serializable; ensembl_mapper
        # is supplied through the context, never through flags.
        flags_for_record = {
            k: v
            for k, v in flags.items()
            if isinstance(v, (bool, int, float, str, dict, list))
        }

        ctx.tracker.record(
            self.name,
            table=ctx.table,
            column=self.column,
            species=self.species,
            flags=flags_for_record,
            counts=dict(report.counts),
            dropped_rows=len(report.dropped_indices),
            sample_unresolved=unresolved_values,
        )
        return out


@dataclass
class DropNa(Step):
    """Drop rows that are NaN/empty in any of the listed columns."""

    name: ClassVar[str] = "dropna"

    columns: list[str]

    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame:
        df = _require_df(df, self.name)
        before = len(df)
        out = df.dropna(subset=self.columns)
        after = len(out)
        ctx.tracker.record(
            self.name,
            table=ctx.table,
            columns=list(self.columns),
            rows_before=before,
            rows_after=after,
            dropped=before - after,
        )
        return out


@dataclass
class FilterRows(Step):
    """Drop rows where `predicate(df) -> Series[bool]` returns False.

    `description` is the human-readable reason recorded in the YAML —
    e.g. "non-empty hgnc_symbol".
    """

    name: ClassVar[str] = "filter_rows"

    predicate: Callable[[pd.DataFrame], pd.Series]
    description: str

    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame:
        df = _require_df(df, self.name)
        before = len(df)
        mask = self.predicate(df)
        out = df[mask]
        after = len(out)
        ctx.tracker.record(
            self.name,
            table=ctx.table,
            description=self.description,
            rows_before=before,
            rows_after=after,
            dropped=before - after,
        )
        return cast(pd.DataFrame, out)


@dataclass
class Rename(Step):
    """Rename columns via a mapping. Records the mapping for provenance."""

    name: ClassVar[str] = "rename"

    mapping: dict[str, str]

    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame:
        df = _require_df(df, self.name)
        # Only record entries whose source column is actually present.
        applied = {k: v for k, v in self.mapping.items() if k in df.columns}
        out = df.rename(columns=applied)
        ctx.tracker.record(
            self.name,
            table=ctx.table,
            mapping=dict(applied),
        )
        return out


@dataclass
class Reorder(Step):
    """Subset and reorder columns to the given list."""

    name: ClassVar[str] = "reorder"

    columns: list[str]

    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame:
        df = _require_df(df, self.name)
        missing = [c for c in self.columns if c not in df.columns]
        if missing:
            raise KeyError(
                f"reorder: columns missing from DataFrame: {missing}; "
                f"available: {list(df.columns)}"
            )
        out = df[list(self.columns)]
        ctx.tracker.record(
            self.name,
            table=ctx.table,
            columns=list(self.columns),
        )
        return cast(pd.DataFrame, out)


@dataclass
class DropColumns(Step):
    """Drop the listed columns. `errors` follows pandas semantics."""

    name: ClassVar[str] = "drop_columns"

    columns: list[str]
    errors: str = "raise"

    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame:
        df = _require_df(df, self.name)
        applied = [c for c in self.columns if c in df.columns]
        out = df.drop(columns=self.columns, errors=self.errors)  # type: ignore[arg-type]
        ctx.tracker.record(
            self.name,
            table=ctx.table,
            columns=applied,
        )
        return out


@dataclass
class TransformColumn(Step):
    """Apply `func` to the values of `column`. `description` is required.

    `func` is called as `func(series) -> series`. Use this for one-off
    string fixups (e.g. trailing-dot removal) — the `description` lands in
    the YAML so users can see what was done.
    """

    name: ClassVar[str] = "transform_column"

    column: str
    func: Callable[[pd.Series], pd.Series]
    description: str

    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame:
        df = _require_df(df, self.name)
        if self.column not in df.columns:
            raise KeyError(
                f"transform_column: {self.column!r} not in DataFrame; "
                f"available: {list(df.columns)}"
            )
        out = df.copy()
        before = out[self.column].copy()
        out[self.column] = self.func(cast(pd.Series, out[self.column]))
        changed = int((before != out[self.column]).fillna(False).sum())
        ctx.tracker.record(
            self.name,
            table=ctx.table,
            column=self.column,
            description=self.description,
            rows_changed=changed,
        )
        return out


@dataclass
class InsertColumn(Step):
    """Add a constant or computed column.

    `value` may be a scalar, a list/Series of correct length, or a callable
    `func(df) -> Series`. `position=None` appends; otherwise the column is
    inserted at the given index.
    """

    name: ClassVar[str] = "insert_column"

    column: str
    value: Any = None
    position: int | None = None

    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame:
        df = _require_df(df, self.name)
        out = df.copy()
        resolved = self.value(out) if callable(self.value) else self.value
        if self.position is None:
            out[self.column] = resolved
        else:
            out.insert(self.position, self.column, resolved)  # type: ignore[arg-type]
        # For scalar values we record the literal; for lists/series we just
        # record the type so the YAML stays compact.
        recorded_value: Any
        if isinstance(resolved, (str, int, float, bool)) or resolved is None:
            recorded_value = resolved
        else:
            recorded_value = f"<{type(resolved).__name__}>"
        ctx.tracker.record(
            "insert_column",
            table=ctx.table,
            column=self.column,
            position=self.position,
            value=recorded_value,
        )
        return out


@dataclass
class WriteCsv(Step):
    """Write the current DataFrame to disk. Pipeline finishes here."""

    name: ClassVar[str] = "write_csv"

    path: Path
    sep: str = ","

    def apply(self, df: pd.DataFrame | None, ctx: "Context") -> pd.DataFrame:
        df = _require_df(df, self.name)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(self.path, sep=self.sep, index=False)
        ctx.tracker.record(
            self.name,
            table=ctx.table,
            destination=self.path.name,
            separator=self.sep,
            rows=len(df),
            columns=list(df.columns),
        )
        return df
