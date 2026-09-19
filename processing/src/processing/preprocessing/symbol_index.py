"""In-memory symbol index for gene-name normalization at preprocessing time.

Loads HGNC and MGI source files into lightweight lookup tables so that
per-dataset preprocess.py scripts can validate and canonicalize gene
symbols without pulling in the full load-db pipeline.
"""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from processing.shared_inputs import require_shared_input


Species = Literal["human", "mouse"]

# Stable gene identifiers a source table may carry next to its symbol column.
# `clean_gene_column(id_columns=...)` resolves them through HGNC's own
# cross-references (human only).
IdKind = Literal["hgnc_id", "entrez_id", "ensembl_id"]
ID_KINDS: tuple[IdKind, ...] = ("hgnc_id", "entrez_id", "ensembl_id")


_MGI_FIELDNAMES = [
    "MGI Marker Accession ID",
    "Marker Symbol",
    "Status",
    "Marker Name",
    "cM Position",
    "Chromosome",
    "Type",
    "Secondary Accession IDs",
    "Entrez Gene ID",
    "Synonyms",
    "Feature Types",
    "Genome Coordinate Start",
    "Genome Coordinate End",
    "Strand",
    "BioTypes",
]


@dataclass
class GeneSymbolNormalizer:
    """Resolve gene names against the HGNC/MGI symbol sets.

    Build via from_paths() or from_env(); not meant to be constructed directly
    by callers (the field defaults exist for testing).
    """

    human_symbols: set[str] = field(default_factory=set)
    human_alias_to_symbol: dict[str, str] = field(default_factory=dict)
    hgnc_id_to_symbol: dict[str, str] = field(default_factory=dict)
    entrez_to_symbol: dict[str, str] = field(default_factory=dict)
    ensembl_to_symbol: dict[str, str] = field(default_factory=dict)
    mouse_symbols: set[str] = field(default_factory=set)
    mouse_alias_to_symbol: dict[str, str] = field(default_factory=dict)
    _mouse_symbols_lower: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_paths(
        cls,
        hgnc_file: Path,
        mgi_file: Path,
    ) -> "GeneSymbolNormalizer":
        rv = cls()
        rv._load_hgnc(require_shared_input(hgnc_file, description="HGNC complete set"))
        rv._load_mgi(require_shared_input(mgi_file, description="MGI EntrezGene"))
        rv._mouse_symbols_lower = {s.lower(): s for s in rv.mouse_symbols}
        return rv

    @classmethod
    def from_env(
        cls,
        hgnc_relpath: str = "homology/hgnc_complete_set.txt",
        mgi_relpath: str = "homology/MGI_EntrezGene.rpt",
    ) -> "GeneSymbolNormalizer":
        try:
            data_dir = Path(os.environ["SSPSYGENE_DATA_DIR"])
        except KeyError as e:
            raise RuntimeError(
                "SSPSYGENE_DATA_DIR is not set; either set it or use "
                "GeneSymbolNormalizer.from_paths(...) with explicit paths."
            ) from e
        return cls.from_paths(
            hgnc_file=data_dir / hgnc_relpath,
            mgi_file=data_dir / mgi_relpath,
        )

    def _load_hgnc(self, fname: Path) -> None:
        with open(fname, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        approved = {row["symbol"] for row in rows if row.get("symbol")}
        self.human_symbols = approved

        alias_to_symbols: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            symbol = row.get("symbol") or ""
            if not symbol:
                continue
            hgnc_id = row.get("hgnc_id") or ""
            if hgnc_id and hgnc_id != "null":
                self.hgnc_id_to_symbol[hgnc_id] = symbol
            entrez_id = (row.get("entrez_id") or "").strip()
            if entrez_id and entrez_id != "null":
                self.entrez_to_symbol[entrez_id] = symbol
            ensembl_id = (row.get("ensembl_gene_id") or "").strip()
            if ensembl_id and ensembl_id != "null":
                self.ensembl_to_symbol[ensembl_id] = symbol
            for col in ("alias_symbol", "prev_symbol"):
                raw = row.get(col) or ""
                if not raw:
                    continue
                for alias in raw.split("|"):
                    alias = alias.strip()
                    if not alias or alias in approved:
                        continue
                    alias_to_symbols[alias].add(symbol)

        # Drop ambiguous aliases (multiple approved symbols claim them).
        for alias, symbols in alias_to_symbols.items():
            if len(symbols) == 1:
                self.human_alias_to_symbol[alias] = next(iter(symbols))

    def _load_mgi(self, fname: Path) -> None:
        approved: set[str] = set()
        withdrawn_to_current: dict[str, str] = {}
        synonym_to_symbols: dict[str, set[str]] = defaultdict(set)

        with open(fname, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t", fieldnames=_MGI_FIELDNAMES)
            for row in reader:
                status = row.get("Status") or ""
                symbol = row.get("Marker Symbol") or ""
                if status == "O":
                    approved.add(symbol)
                    synonyms_raw = row.get("Synonyms") or ""
                    for syn in synonyms_raw.split("|"):
                        syn = syn.strip()
                        if syn and syn != symbol:
                            synonym_to_symbols[syn].add(symbol)
                elif status == "W":
                    marker_name = row.get("Marker Name") or ""
                    if " = " in marker_name:
                        new_symbol = marker_name.split("=", 1)[1].strip()
                        if symbol and new_symbol:
                            withdrawn_to_current[symbol] = new_symbol

        self.mouse_symbols = approved

        for old, new in withdrawn_to_current.items():
            if old in approved:
                continue
            if new in approved:
                self.mouse_alias_to_symbol[old] = new

        for syn, symbols in synonym_to_symbols.items():
            if syn in approved or syn in self.mouse_alias_to_symbol:
                continue
            if len(symbols) == 1:
                self.mouse_alias_to_symbol[syn] = next(iter(symbols))

    def is_symbol(self, name: str, species: Species) -> bool:
        if species == "human":
            return name in self.human_symbols
        if species == "mouse":
            return name in self.mouse_symbols
        raise ValueError(f"Invalid species: {species!r}")

    def resolve(self, name: str, species: Species) -> str | None:
        """Return the approved symbol for `name`, or None if unrecognized.

        Handles direct symbol hits, alias_symbol/prev_symbol (human),
        and withdrawn/synonym mapping (mouse). Mouse lookup also tries a
        case-insensitive fallback so that values like `Slc30a3` recover
        when the source file uses `Slc30A3`-style casing.
        """
        if not name:
            return None
        if species == "human":
            if name in self.human_symbols:
                return name
            return self.human_alias_to_symbol.get(name)
        if species == "mouse":
            if name in self.mouse_symbols:
                return name
            if name in self.mouse_alias_to_symbol:
                return self.mouse_alias_to_symbol[name]
            return self._mouse_symbols_lower.get(name.lower())
        raise ValueError(f"Invalid species: {species!r}")

    def resolve_hgnc_id(self, hgnc_id: str) -> str | None:
        return self.hgnc_id_to_symbol.get(hgnc_id)

    def resolve_id(self, value: object, kind: IdKind) -> str | None:
        """Approved human symbol for a stable ID, via HGNC's cross-references.

        Tolerates the shapes source tables store IDs in: `HGNC:5`, `5` or
        `5.0` for HGNC IDs (spreadsheets turn them into floats), `7157` or
        `7157.0` for Entrez, and versioned `ENSG….12` for Ensembl. Returns
        None for blanks and for IDs HGNC doesn't list.
        """
        text = normalize_id(value, kind)
        if text is None:
            return None
        if kind == "hgnc_id":
            return self.hgnc_id_to_symbol.get(text)
        if kind == "entrez_id":
            return self.entrez_to_symbol.get(text)
        if kind == "ensembl_id":
            return self.ensembl_to_symbol.get(text)
        raise ValueError(f"Invalid id kind: {kind!r}; expected one of {ID_KINDS}")


def normalize_id(value: object, kind: IdKind) -> str | None:
    """Canonical text form of a stable gene ID, or None if blank/malformed."""
    if value is None or (isinstance(value, float) and value != value):
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "null", "-"):
        return None
    if kind == "ensembl_id":
        return text.split(".", 1)[0] if text.startswith("ENS") else None
    if kind == "hgnc_id" and text.upper().startswith("HGNC:"):
        text = text[5:]
    if text.endswith(".0"):
        text = text[:-2]
    if not text.isdigit():
        return None
    return f"HGNC:{text}" if kind == "hgnc_id" else text
