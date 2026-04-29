"""DataFrame-level convenience wrapper for gene-name cleanup."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from processing.my_logger import get_sspsygene_logger
from processing.preprocessing import helpers
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
    excel_demangle: bool = False,
    strip_make_unique: bool = False,
    split_symbol_ensg: bool = False,
    drop_non_symbols: bool = False,
) -> tuple[pd.DataFrame, CleanReport]:
    """Resolve and annotate a gene-name column.

    Returns (modified_df, report). The modified DataFrame:
      - has values in `column` replaced with the canonical symbol when
        a resolution succeeded;
      - has a new `_<column>_resolution` column with the per-row tag;
      - drops rows whose value matched is_non_symbol_identifier when
        drop_non_symbols=True (the dropped indices are returned via
        the report).

    The empty / NaN values pass through untouched and are tagged
    `passed_through`.
    """
    if column not in df.columns:
        raise KeyError(f"column {column!r} not in DataFrame columns: {list(df.columns)}")

    out = df.copy()
    new_values: list[object] = []
    resolutions: list[str] = []
    drop_idx: list[int] = []
    counts: Counter[str] = Counter()

    for idx, raw in zip(out.index, out[column].tolist()):
        if pd.isna(raw) or raw == "":
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
