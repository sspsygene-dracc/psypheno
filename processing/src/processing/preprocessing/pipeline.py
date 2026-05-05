"""Composable preprocessing pipeline + provenance tracker.

Per-dataset `preprocess.py` scripts compose a `Pipeline` of `Step`s that
read a raw input, clean it, and write the result. Every step records an
`ActionRecord` on a shared `Tracker`. At the end of `Pipeline.run()` the
tracker automatically emits a per-table sidecar
`<output>.preprocessing.yaml` next to the cleaned data file (#158); the
wrangler does not need an explicit `tracker.write(...)` call.

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
    # Sidecar Supp_1_all_cleaned.csv.preprocessing.yaml has been written.

One `Tracker` per dataset; one `Pipeline` per output table; multiple
pipelines share a tracker so global state stays coherent. For multi-sheet
patterns that pd.concat sub-pipelines into one output, use
`tracker.write_concat(output_path, inputs=[...], **summary)` to record
the concat and emit the sidecar in one call. See
`processing/preprocessing/steps.py` for the built-in step types.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

import pandas as pd
import yaml

from processing.preprocessing.ensembl_index import EnsemblToSymbolMapper
from processing.preprocessing.gencode_clone_index import GencodeCloneIndex
from processing.preprocessing.symbol_index import GeneSymbolNormalizer, Species

if TYPE_CHECKING:
    from processing.preprocessing.steps import Step


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
    """Collects ActionRecords across all pipelines for a dataset.

    Each output table gets its own sidecar `<output>.preprocessing.yaml`
    written next to the cleaned data file. Auto-emitted by
    `Pipeline.run()` (last `WriteCsv` step), `copy_file()`, and
    `tracker.write_concat(...)`.
    """

    inputs: list[str] = field(default_factory=list)
    actions: list[ActionRecord] = field(default_factory=list)

    def record(self, step: str, *, table: str | None = None, **summary: Any) -> None:
        self.actions.append(ActionRecord(step=step, table=table, summary=summary))

    def note_input(self, path: str) -> None:
        if path not in self.inputs:
            self.inputs.append(path)

    def _actions_for(self, table_key: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for rec in self.actions:
            if rec.table != table_key:
                continue
            entry: dict[str, Any] = {"step": rec.step}
            entry.update(rec.summary)
            out.append(entry)
        return out

    def _derive_inputs(self, action_entries: list[dict[str, Any]]) -> list[str]:
        # Per-table inputs: prefer the read_csv source for this output; if
        # the pipeline started from_dataframe (no read_csv), fall back to
        # the dataset-wide inputs list.
        derived: list[str] = []
        for entry in action_entries:
            if entry.get("step") == "read_csv":
                src = entry.get("source")
                if isinstance(src, str) and src not in derived:
                    derived.append(src)
        if derived:
            return derived
        return list(self.inputs)

    def write_sidecar(
        self,
        output_path: Path,
        *,
        table_key: str | None = None,
        inputs: list[str] | None = None,
    ) -> Path:
        """Emit `<output_path>.preprocessing.yaml` next to the data file.

        `table_key` defaults to `output_path.name` — the convention used
        by both `Pipeline` (where `Pipeline.name` matches the output
        basename) and the wrangler-facing `write_concat` helper.
        Returns the sidecar path.
        """
        output_path = Path(output_path)
        key = table_key if table_key is not None else output_path.name
        action_entries = self._actions_for(key)
        resolved_inputs = inputs if inputs is not None else self._derive_inputs(action_entries)
        payload: dict[str, Any] = {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "output": output_path.name,
            "inputs": list(resolved_inputs),
            "actions": action_entries,
        }
        sidecar = output_path.parent / (output_path.name + ".preprocessing.yaml")
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        with sidecar.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                payload,
                f,
                sort_keys=False,
                allow_unicode=True,
                width=100,
            )
        return sidecar

    def write_concat(
        self,
        output_path: Path,
        *,
        inputs: list[str] | None = None,
        **summary: Any,
    ) -> Path:
        """Record a `concat_and_write` action and emit a sidecar.

        Used by multi-sheet preprocess.py scripts (e.g.
        hsc-asd-organoid-m5) that build N sub-pipelines and pd.concat
        their outputs into one combined file. The wrangler calls this
        once after the manual `to_csv`; it tags the action with
        `output_path.name` and writes the sidecar in one shot.
        """
        output_path = Path(output_path)
        self.record(
            "concat_and_write",
            table=output_path.name,
            destination=output_path.name,
            **summary,
        )
        return self.write_sidecar(output_path, inputs=inputs)


@dataclass
class Context:
    """Per-pipeline execution context handed to each Step.apply()."""

    tracker: Tracker
    table: str | None
    normalizer: GeneSymbolNormalizer | None
    ensembl_mapper: EnsemblToSymbolMapper | None
    gencode_clone_index: GencodeCloneIndex | None = None


class Pipeline:
    """A chain of `Step`s that produces one output table.

    Construct one Pipeline per output file. Multiple pipelines for the
    same dataset can share a Tracker; their actions all land in the same
    `preprocessing.yaml`.

    The auxiliary mappers (`ensembl_mapper`, `gencode_clone_index`) are
    auto-instantiated from `SSPSYGENE_DATA_DIR` lazily on first
    `clean_gene` if not explicitly supplied. Pass them in only to use a
    test fixture or a non-standard data directory; explicit `None`
    cannot be distinguished from "not supplied", so to truly disable a
    mapper either omit the corresponding `resolve_*` flag or set it to
    False on the per-call `clean_gene(...)`.
    """

    def __init__(
        self,
        name: str,
        *,
        tracker: Tracker,
        normalizer: GeneSymbolNormalizer | None = None,
        ensembl_mapper: EnsemblToSymbolMapper | None = None,
        gencode_clone_index: GencodeCloneIndex | None = None,
    ) -> None:
        self.name = name
        self.tracker = tracker
        self.normalizer = normalizer
        self._ensembl_mapper = ensembl_mapper
        self._gencode_clone_index = gencode_clone_index
        self._mappers_loaded = False
        self.steps: list[Step] = []

    def _ensure_mappers(self) -> None:
        """Lazily auto-instantiate aux mappers from SSPSYGENE_DATA_DIR.

        Idempotent: only the first call attempts construction. Failures
        (missing env var, missing files) leave the mapper as None and
        the corresponding resolver becomes a silent no-op at
        clean_gene_column time.
        """
        if self._mappers_loaded:
            return
        if self._ensembl_mapper is None:
            try:
                self._ensembl_mapper = EnsemblToSymbolMapper.from_env()
            except (RuntimeError, FileNotFoundError):
                pass
        if self._gencode_clone_index is None:
            try:
                self._gencode_clone_index = GencodeCloneIndex.from_env()
            except (RuntimeError, FileNotFoundError):
                pass
        self._mappers_loaded = True

    @property
    def ensembl_mapper(self) -> EnsemblToSymbolMapper | None:
        self._ensure_mappers()
        return self._ensembl_mapper

    @property
    def gencode_clone_index(self) -> GencodeCloneIndex | None:
        self._ensure_mappers()
        return self._gencode_clone_index

    def add(self, step: Step) -> Pipeline:
        self.steps.append(step)
        return self

    # --- Builder methods. Each delegates to a Step dataclass in
    # steps.py; the corresponding constructor signatures are mirrored
    # here so call-site type checking flags wrong arg shapes (vs the
    # previous `**kw: Any` / `predicate: Any` opacity).
    # ----------------------------------------------------------------

    def read_csv(
        self,
        path: str | Path,
        *,
        sep: str = ",",
        dtype: Any = str,
        **kw: Any,
    ) -> Pipeline:
        # `dtype` and `**kw` are pandas pass-throughs; pandas itself
        # accepts a wide Union (type / Mapping / extension dtype / None)
        # and doesn't expose a TypedDict for the rest of read_csv's
        # kwargs, so these stay `Any`.
        from processing.preprocessing.steps import ReadCsv

        return self.add(ReadCsv(path=Path(path), sep=sep, dtype=dtype, read_kw=kw))

    def from_dataframe(
        self,
        df: pd.DataFrame,
        *,
        label: str | None = None,
    ) -> Pipeline:
        from processing.preprocessing.steps import FromDataFrame

        return self.add(FromDataFrame(df=df, label=label))

    def read_tsv(
        self, path: str | Path, *, dtype: Any = str, **kw: Any
    ) -> Pipeline:
        return self.read_csv(path, sep="\t", dtype=dtype, **kw)

    def clean_gene(
        self,
        column: str,
        *,
        species: Species,
        resolve_hgnc_id: bool = True,
        excel_demangle: bool = True,
        strip_make_unique: bool = True,
        split_symbol_ensg: bool = True,
        manual_aliases: dict[str, str] | None = None,
        drop_non_symbols: bool = False,
        resolve_via_ensembl_map: bool = True,
        resolve_gencode_clone: bool = True,
    ) -> Pipeline:
        # Defaults mirror `clean_gene_column`'s opt-out behavior — call
        # sites override individual flags with `=False` when needed.
        from processing.preprocessing.steps import CleanGeneColumnStep

        return self.add(
            CleanGeneColumnStep(
                column=column,
                species=species,
                resolve_hgnc_id=resolve_hgnc_id,
                excel_demangle=excel_demangle,
                strip_make_unique=strip_make_unique,
                split_symbol_ensg=split_symbol_ensg,
                manual_aliases=manual_aliases,
                drop_non_symbols=drop_non_symbols,
                resolve_via_ensembl_map=resolve_via_ensembl_map,
                resolve_gencode_clone=resolve_gencode_clone,
            )
        )

    def dropna(self, columns: str | list[str]) -> Pipeline:
        from processing.preprocessing.steps import DropNa

        if isinstance(columns, str):
            columns = [columns]
        return self.add(DropNa(columns=list(columns)))

    def filter_rows(
        self,
        predicate: Callable[[pd.DataFrame], pd.Series],
        *,
        description: str,
    ) -> Pipeline:
        from processing.preprocessing.steps import FilterRows

        return self.add(FilterRows(predicate=predicate, description=description))

    def rename(self, mapping: dict[str, str]) -> Pipeline:
        from processing.preprocessing.steps import Rename

        return self.add(Rename(mapping=dict(mapping)))

    def reorder(self, columns: list[str]) -> Pipeline:
        from processing.preprocessing.steps import Reorder

        return self.add(Reorder(columns=list(columns)))

    def drop_columns(
        self,
        columns: str | list[str],
        *,
        errors: Literal["raise", "ignore"] = "raise",
    ) -> Pipeline:
        from processing.preprocessing.steps import DropColumns

        if isinstance(columns, str):
            columns = [columns]
        return self.add(DropColumns(columns=list(columns), errors=errors))

    def transform_column(
        self,
        column: str,
        func: Callable[[pd.Series], pd.Series],
        *,
        description: str,
    ) -> Pipeline:
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
    ) -> Pipeline:
        # `value` accepts scalar / list / Series / callable per
        # InsertColumn — the union is genuinely heterogeneous so
        # tightening below `Any` would just push casts onto callers.
        from processing.preprocessing.steps import InsertColumn

        return self.add(InsertColumn(column=name, value=value, position=position))

    def write_csv(self, path: str | Path, *, sep: str = ",") -> Pipeline:
        from processing.preprocessing.steps import WriteCsv

        return self.add(WriteCsv(path=Path(path), sep=sep))

    def write_tsv(self, path: str | Path) -> Pipeline:
        return self.write_csv(path, sep="\t")

    def run(self) -> pd.DataFrame:
        from processing.preprocessing.steps import WriteCsv

        ctx = Context(
            tracker=self.tracker,
            table=self.name,
            normalizer=self.normalizer,
            ensembl_mapper=self.ensembl_mapper,
            gencode_clone_index=self.gencode_clone_index,
        )
        df: pd.DataFrame | None = None
        for step in self.steps:
            df = step.apply(df, ctx)
        if df is None:
            raise ValueError(
                f"Pipeline {self.name!r} ended without a DataFrame — did you "
                "forget a read_*/write_* step?"
            )
        # Auto-emit the per-output sidecar based on the last WriteCsv. A
        # pipeline without a write step (rare; only the hsc-asd sub-
        # pipelines do this) skips emission — its caller handles the
        # eventual aggregate via tracker.write_concat.
        for step in reversed(self.steps):
            if isinstance(step, WriteCsv):
                self.tracker.write_sidecar(step.path, table_key=self.name)
                break
        return df


def copy_file(src: str | Path, dst: str | Path, *, tracker: Tracker) -> None:
    """Pass-through copy of a companion file, recorded in the tracker.

    Used for files that need to ship to load-db unchanged (e.g. a patient
    list that's referenced from another table). The `dst` filename is the
    table key in the provenance YAML, and a sidecar
    `<dst>.preprocessing.yaml` is written next to it.
    """
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    tracker.note_input(src.name)
    tracker.record("copy_file", table=dst.name, source=src.name)
    tracker.write_sidecar(dst, inputs=[src.name])
