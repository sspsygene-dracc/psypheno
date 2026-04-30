"""DataFrame-level convenience wrapper for gene-name cleanup."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from processing.my_logger import get_sspsygene_logger
from processing.preprocessing import helpers
from processing.preprocessing.ensembl_index import EnsemblToSymbolMapper
from processing.preprocessing.symbol_index import GeneSymbolNormalizer, Species


@dataclass
class CleanReport:
    """Summary of a clean_gene_column() run.

    `resolutions` is the per-row tag column (one entry per input row, in
    order). `counts` is a tally of those tags. `dropped_indices` is the
    list of row indices removed when drop_non_symbols=True.
    """

    column: str
    species: Species
    resolutions: list[str] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    dropped_indices: list[int] = field(default_factory=list)

    def summary(self) -> str:
        rescued = sum(v for k, v in self.counts.items() if k.startswith("rescued_"))
        passed = self.counts.get("passed_through", 0)
        unresolved = self.counts.get("unresolved", 0)
        non_symbol = sum(
            v for k, v in self.counts.items() if k.startswith("non_symbol_")
        )
        return (
            f"clean_gene_column[{self.column}, {self.species}]: "
            f"passed-through {passed} / rescued {rescued} / "
            f"non-symbol {non_symbol} / unresolved {unresolved} / "
            f"dropped {len(self.dropped_indices)}"
        )


def clean_gene_column(
    df: pd.DataFrame,
    column: str,
    *,
    species: Species,
    normalizer: GeneSymbolNormalizer,
    resolve_hgnc_id: bool = False,
    excel_demangle: bool = False,
    strip_make_unique: bool = False,
    split_symbol_ensg: bool = False,
    manual_aliases: dict[str, str] | None = None,
    drop_non_symbols: bool = False,
    ensembl_mapper: EnsemblToSymbolMapper | None = None,
    resolve_via_ensembl_map: bool = False,
) -> tuple[pd.DataFrame, CleanReport]:
    """Resolve and annotate a gene-name column.

    Returns (modified_df, report). The modified DataFrame:
      - keeps the original (pre-cleaner) value in `<column>_raw`;
      - replaces values in `column` with the canonical symbol when a
        resolution succeeded;
      - adds `_<column>_resolution` with the per-row tag;
      - drops rows whose value matched is_non_symbol_identifier when
        drop_non_symbols=True (the dropped indices are returned via
        the report).

    Empty / NaN values pass through untouched and are tagged
    `passed_through`.

    `manual_aliases` is a wrangler-supplied last-resort rescue map for
    retired symbols whose canonical successor cannot be picked
    automatically (e.g. `NOV → CCN3`). It runs AFTER the auto-rescues
    and BEFORE `is_non_symbol_identifier`, and resolves the alias
    target through the normalizer to guard against typos.

    `resolve_via_ensembl_map=True` rescues raw `ENSG…`/`ENSMUSG…`
    values that map to a known approved symbol in the supplied
    `ensembl_mapper`. Tagged `rescued_ensembl_map`. Orphan IDs (no
    symbol mapping) fall through to the `non_symbol_ensembl_*`
    classification.
    """
    if resolve_via_ensembl_map and ensembl_mapper is None:
        raise ValueError(
            "resolve_via_ensembl_map=True requires an ensembl_mapper; "
            "pass EnsemblToSymbolMapper.from_env() (or from_paths)."
        )

    if column not in df.columns:
        raise KeyError(f"column {column!r} not in DataFrame columns: {list(df.columns)}")

    raw_col = f"{column}_raw"
    if raw_col in df.columns:
        raise KeyError(
            f"column {raw_col!r} already exists in DataFrame; clean_gene_column "
            "needs to write the raw values there. Rename or drop the existing "
            "column before calling."
        )

    aliases = manual_aliases or {}

    out = df.copy()
    raw_values: list[object] = list(out[column].tolist())
    new_values: list[object] = []
    resolutions: list[str] = []
    drop_idx: list[int] = []
    counts: Counter[str] = Counter()

    for idx, raw in zip(out.index, raw_values):
        if raw is None or (isinstance(raw, float) and math.isnan(raw)) or raw == "":
            new_values.append(raw)
            resolutions.append("passed_through")
            counts["passed_through"] += 1
            continue

        name = str(raw).strip()
        resolved = normalizer.resolve(name, species)
        if resolved is not None:
            new_values.append(resolved)
            resolutions.append("passed_through")
            counts["passed_through"] += 1
            continue

        if resolve_hgnc_id and name.startswith("HGNC:"):
            rescued = normalizer.resolve_hgnc_id(name)
            if rescued is not None:
                new_values.append(rescued)
                resolutions.append("rescued_hgnc_id")
                counts["rescued_hgnc_id"] += 1
                continue

        if excel_demangle:
            rescued = helpers.excel_demangle(name, normalizer, species)
            if rescued is not None:
                new_values.append(rescued)
                resolutions.append("rescued_excel")
                counts["rescued_excel"] += 1
                continue

        if strip_make_unique:
            rescued = helpers.strip_make_unique_suffix(name, normalizer, species)
            if rescued is not None:
                new_values.append(rescued)
                resolutions.append("rescued_make_unique")
                counts["rescued_make_unique"] += 1
                continue

        if split_symbol_ensg:
            split = helpers.split_symbol_ensg(name)
            if split is not None:
                symbol_part, _ensg = split
                rescued = normalizer.resolve(symbol_part, species)
                if rescued is not None:
                    new_values.append(rescued)
                    resolutions.append("rescued_symbol_ensg")
                    counts["rescued_symbol_ensg"] += 1
                    continue

        if name in aliases:
            target = aliases[name]
            rescued = normalizer.resolve(target, species)
            if rescued is None:
                raise ValueError(
                    f"manual_aliases: target {target!r} (for {name!r}) is not a "
                    f"current approved {species} symbol. Pick a different "
                    "successor or drop the entry."
                )
            new_values.append(rescued)
            resolutions.append("rescued_manual_alias")
            counts["rescued_manual_alias"] += 1
            continue

        if resolve_via_ensembl_map:
            assert ensembl_mapper is not None
            rescued = ensembl_mapper.resolve_ensg(name, species)
            if rescued is not None:
                resolved_symbol = normalizer.resolve(rescued, species)
                if resolved_symbol is not None:
                    new_values.append(resolved_symbol)
                    resolutions.append("rescued_ensembl_map")
                    counts["rescued_ensembl_map"] += 1
                    continue

        # New rescue helpers (e.g. #124's resolve_gencode_clone) MUST be
        # added above this classification step so the silencer remains a
        # backstop, not a short-circuit.
        category = helpers.is_non_symbol_identifier(name)
        if category is not None:
            tag = f"non_symbol_{category}"
            counts[tag] += 1
            if drop_non_symbols:
                drop_idx.append(idx)
                new_values.append(raw)
                resolutions.append(tag)
                continue
            new_values.append(raw)
            resolutions.append(tag)
            continue

        new_values.append(raw)
        resolutions.append("unresolved")
        counts["unresolved"] += 1

    out[raw_col] = raw_values
    out[column] = new_values
    out[f"_{column}_resolution"] = resolutions

    if drop_idx:
        out = out.drop(index=drop_idx)

    report = CleanReport(
        column=column,
        species=species,
        resolutions=resolutions,
        counts=counts,
        dropped_indices=drop_idx,
    )
    get_sspsygene_logger().info(report.summary())
    return out, report
