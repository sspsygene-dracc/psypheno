"""In-memory GENCODE clone-name index for preprocessing.

Mirrors the shape of `symbol_index.GeneSymbolNormalizer` and
`ensembl_index.EnsemblToSymbolMapper`: build via `from_paths()` or
`from_env()`, then call `resolve_clone(name)` to map a legacy GENCODE/HAVANA
clone identifier (`RP11-…`, `CTD-…`, `KB-…`, `XXbac-…`, etc.) to its
current state.

The underlying TSV (`data/homology/gencode_clone_map.tsv`) is built once
by `processing.build_gencode_clone_map` from a pinned GENCODE GTF release
plus the HGNC `ensembl_gene_id` column. Format:

    clone_name<TAB>resolution<TAB>kind

where `kind` is one of:

  * `hgnc_symbol`           — clone has been promoted to a current HGNC
                              symbol; `resolution` holds that symbol.
  * `current_ensg`          — locus is still in current Ensembl but has
                              no HGNC symbol; `resolution` holds the ENSG
                              (a stable anchor for #119's resolver and
                              Tier B's silencer).
  * `current_ac_accession`  — clone was renamed to a current
                              AC/AL/AP accession; `resolution` holds it.

The fourth `kind` from #139 (`retired`) is intentionally not produced
by the initial build — clones absent from the TSV simply fall through
to the existing Tier B `gencode_clone` silencer at runtime, with no
behavioral regression.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


CloneKind = Literal["hgnc_symbol", "current_ensg", "current_ac_accession"]


_VALID_KINDS: frozenset[str] = frozenset(
    {"hgnc_symbol", "current_ensg", "current_ac_accession"}
)


@dataclass
class GencodeCloneIndex:
    """Resolve legacy GENCODE/HAVANA clone identifiers to a current anchor.

    Build via `from_paths()` or `from_env()`; the field default exists
    only for testing.
    """

    clone_to_status: dict[str, tuple[CloneKind, str]] = field(default_factory=dict)

    @classmethod
    def from_paths(cls, tsv_path: Path) -> "GencodeCloneIndex":
        rv = cls()
        rv._load(tsv_path)
        return rv

    @classmethod
    def from_env(
        cls, tsv_relpath: str = "homology/gencode_clone_map.tsv"
    ) -> "GencodeCloneIndex":
        try:
            data_dir = Path(os.environ["SSPSYGENE_DATA_DIR"])
        except KeyError as e:
            raise RuntimeError(
                "SSPSYGENE_DATA_DIR is not set; either set it or use "
                "GencodeCloneIndex.from_paths(...) with explicit paths."
            ) from e
        return cls.from_paths(tsv_path=data_dir / tsv_relpath)

    def _load(self, fname: Path) -> None:
        with open(fname, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                name = (row.get("clone_name") or "").strip()
                resolution = (row.get("resolution") or "").strip()
                kind = (row.get("kind") or "").strip()
                if not name or not resolution or kind not in _VALID_KINDS:
                    continue
                # Last write wins for duplicate clone_names. Inputs are
                # built deterministically from a single GTF + HGNC pass,
                # so duplicates indicate a bug in the build script — we
                # don't try to recover here.
                self.clone_to_status[name] = (kind, resolution)  # type: ignore[assignment]

    def resolve_clone(self, name: str) -> tuple[CloneKind, str] | None:
        """Return (kind, resolution) for a clone name, or None.

        None means: this name is not in the prebuilt map. Callers should
        treat that the same as today's behavior — fall through to the
        Tier B `gencode_clone` silencer.
        """
        if not name:
            return None
        return self.clone_to_status.get(name)
