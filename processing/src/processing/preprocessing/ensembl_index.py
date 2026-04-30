"""In-memory Ensembl-ID to gene-symbol index for preprocessing.

Mirrors the shape of `symbol_index.GeneSymbolNormalizer`: build via
`from_paths()` or `from_env()`, then call `resolve_ensg(...)` to map a raw
`ENSG…` / `ENSMUSG…` ID to its current approved symbol.

The mapping is built directly from upstream HGNC + Alliance source files —
*not* from the `central_gene` table — so it is available at preprocess time,
before `load-db` runs. After this lands, `web/lib/ensembl-symbol-resolver.ts`
becomes redundant: stored values are already symbols.
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from processing.preprocessing.symbol_index import Species


_ENSG_VERSIONED_RE = re.compile(r"^(ENS(?:MUS)?G\d+)(?:\.\d+)?$")


@dataclass
class EnsemblToSymbolMapper:
    """Resolve `ENSG…` / `ENSMUSG…` IDs to approved symbols.

    Build via `from_paths()` or `from_env()`; the field defaults exist
    only for testing. Versioned IDs (e.g. `ENSG00000123456.4`) are handled
    by stripping the trailing `.N` before lookup.
    """

    human_ensg_to_symbol: dict[str, str] = field(default_factory=dict)
    mouse_ensg_to_symbol: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_paths(
        cls,
        hgnc_file: Path,
        alliance_homology_file: Path,
    ) -> "EnsemblToSymbolMapper":
        rv = cls()
        rv._load_hgnc(hgnc_file)
        rv._load_alliance(alliance_homology_file)
        return rv

    @classmethod
    def from_env(
        cls,
        hgnc_relpath: str = "homology/hgnc_complete_set.txt",
        alliance_homology_relpath: str = "homology/HGNC_AllianceHomology.rpt",
    ) -> "EnsemblToSymbolMapper":
        try:
            data_dir = Path(os.environ["SSPSYGENE_DATA_DIR"])
        except KeyError as e:
            raise RuntimeError(
                "SSPSYGENE_DATA_DIR is not set; either set it or use "
                "EnsemblToSymbolMapper.from_paths(...) with explicit paths."
            ) from e
        return cls.from_paths(
            hgnc_file=data_dir / hgnc_relpath,
            alliance_homology_file=data_dir / alliance_homology_relpath,
        )

    def _load_hgnc(self, fname: Path) -> None:
        with open(fname, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                symbol = row.get("symbol") or ""
                ensg = row.get("ensembl_gene_id") or ""
                if not symbol or not ensg or ensg == "null":
                    continue
                self.human_ensg_to_symbol[ensg] = symbol

    def _load_alliance(self, fname: Path) -> None:
        with open(fname, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                symbol = row.get("Marker Symbol") or ""
                ensg = row.get("Ensembl Gene ID") or ""
                if not symbol or not ensg or ensg == "null":
                    continue
                if not ensg.startswith("ENSMUSG"):
                    continue
                self.mouse_ensg_to_symbol[ensg] = symbol

    def resolve_ensg(self, value: str, species: Species) -> str | None:
        """Return the approved symbol for an `ENSG…`/`ENSMUSG…` value.

        Returns None when the value is not a recognized Ensembl ID, or
        when no symbol mapping exists for it. Versioned IDs
        (`ENSG00000123456.4`) are resolved by stripping the version
        suffix before lookup.
        """
        if not value:
            return None
        m = _ENSG_VERSIONED_RE.match(value)
        if m is None:
            return None
        bare = m.group(1)
        if species == "human":
            if not bare.startswith("ENSG"):
                return None
            return self.human_ensg_to_symbol.get(bare)
        if species == "mouse":
            if not bare.startswith("ENSMUSG"):
                return None
            return self.mouse_ensg_to_symbol.get(bare)
        raise ValueError(f"Invalid species: {species!r}")
