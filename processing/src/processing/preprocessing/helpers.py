"""Pure helpers for gene-name cleanup.

All helpers are stateless except for ones that look up against a
GeneSymbolNormalizer; those take the normalizer as an argument so the
helpers stay easy to unit-test.
"""

from __future__ import annotations

import re
from typing import Callable, Literal

from processing.preprocessing.symbol_index import GeneSymbolNormalizer, Species


_EXCEL_CLASSIC_RE = re.compile(r"^(\d{1,2})-(Mar|Sep|Dec)$", re.IGNORECASE)
_EXCEL_ISO_RE = re.compile(r"^\d{4}-(\d{2})-(\d{2})$")

_ISO_MONTH_TO_NAME = {"03": "Mar", "09": "Sep", "12": "Dec"}

_MONTH_TO_CANDIDATES: dict[str, list[str]] = {
    "Mar": ["MARCHF{n}", "MARCH{n}"],
    "Sep": ["SEPTIN{n}", "SEPT{n}"],
    "Dec": ["DELEC{n}", "DEC{n}"],
}


_ENSG_RE = re.compile(r"^ENSG\d+(?:\.\d+)?$")
_ENSMUSG_RE = re.compile(r"^ENSMUSG\d+(?:\.\d+)?$")
_CONTIG_RE = re.compile(
    r"^(((C[RU]|F[OP]|AUXG|BX|A[CDFJLP])\d{6,8}\.\d{1,2})|([UZ]\d{5}\.\d))$"
)
_GENCODE_CLONE_RE = re.compile(
    r"^(RP\d+|CT[ABCD]|KB|GS1|LA16c|LL0XNC01|LL22NC03|WI2|XX(bac|yac|cos)|hsa)-[\w.-]+$"
)
_GENBANK_RE = re.compile(r"^[A-Z]{1,2}\d{5,6}(\.\d+)?$")

_MAKE_UNIQUE_RE = re.compile(r"^(.+?)\.(\d+)$")
_SYMBOL_ENSG_RE = re.compile(r"^(.+?)_(ENSG\d+(?:\.\d+)?)$")


NonSymbolCategory = Literal[
    "ensembl_human",
    "ensembl_mouse",
    "contig",
    "gencode_clone",
    "genbank_accession",
]


def excel_demangle(
    name: str, normalizer: GeneSymbolNormalizer, species: Species = "human"
) -> str | None:
    """Recover an Excel-mangled gene symbol, or return None.

    Handles two forms:
      * Classic short form: `1-Mar`, `9-Sep`, `1-Dec` (number-month).
      * ISO-date form: `2023-09-04` (year-month-day; gene number is day).

    Resolution is verified against `normalizer` so we never invent symbols.
    """
    if not name:
        return None

    classic = _EXCEL_CLASSIC_RE.match(name)
    if classic is not None:
        gene_n = int(classic.group(1))
        month = classic.group(2).capitalize()
        return _resolve_month_candidate(month, gene_n, normalizer, species)

    iso = _EXCEL_ISO_RE.match(name)
    if iso is not None:
        month_num, day_str = iso.group(1), iso.group(2)
        month = _ISO_MONTH_TO_NAME.get(month_num)
        if month is None:
            return None
        return _resolve_month_candidate(month, int(day_str), normalizer, species)

    return None


def _resolve_month_candidate(
    month: str, gene_n: int, normalizer: GeneSymbolNormalizer, species: Species
) -> str | None:
    candidates = _MONTH_TO_CANDIDATES.get(month, [])
    for tmpl in candidates:
        candidate = tmpl.format(n=gene_n)
        resolved = normalizer.resolve(candidate, species)
        if resolved is not None:
            return resolved
    return None


def is_non_symbol_identifier(name: str) -> NonSymbolCategory | None:
    """Classify obviously-not-a-gene-symbol values.

    Returns a category tag that callers can use to silence warnings or
    drop rows. Order matters: contig is checked before the more general
    GenBank pattern so that AUXG01000058.1 isn't misclassified.
    """
    if not name:
        return None
    if _ENSG_RE.match(name):
        return "ensembl_human"
    if _ENSMUSG_RE.match(name):
        return "ensembl_mouse"
    if _CONTIG_RE.match(name):
        return "contig"
    if _GENCODE_CLONE_RE.match(name):
        return "gencode_clone"
    if _GENBANK_RE.match(name):
        return "genbank_accession"
    return None


def _make_category_predicate(category: NonSymbolCategory) -> Callable[[str], bool]:
    def predicate(name: str) -> bool:
        return is_non_symbol_identifier(name) == category

    predicate.__name__ = f"is_{category}"
    return predicate


# Public, explicit map from category name → predicate. The YAML loader uses
# this to validate `non_resolving.drop_patterns` / `record_patterns` entries.
NON_SYMBOL_CATEGORIES: dict[str, Callable[[str], bool]] = {
    "ensembl_human": _make_category_predicate("ensembl_human"),
    "ensembl_mouse": _make_category_predicate("ensembl_mouse"),
    "contig": _make_category_predicate("contig"),
    "gencode_clone": _make_category_predicate("gencode_clone"),
    "genbank_accession": _make_category_predicate("genbank_accession"),
}


def strip_make_unique_suffix(
    name: str, normalizer: GeneSymbolNormalizer, species: Species = "human"
) -> str | None:
    """Strip an R `make.unique` suffix (`.1`, `.2`, ...) iff safe.

    Only collapses `MATR3.1` → `MATR3` when:
      (a) the un-suffixed form resolves to a known symbol, AND
      (b) the suffixed form does NOT resolve.

    Guard (b) prevents corrupting legitimate `.N`-suffixed names like
    GENCODE clones (`RP11-783K16.5`). Guard (a) prevents inventing a
    symbol when the un-suffixed form is itself a non-symbol (e.g.
    GenBank accession `KC877982` from `KC877982.1`).
    """
    if not name:
        return None
    m = _MAKE_UNIQUE_RE.match(name)
    if m is None:
        return None
    base = m.group(1)
    if normalizer.resolve(name, species) is not None:
        return None
    return normalizer.resolve(base, species)


def split_symbol_ensg(name: str) -> tuple[str, str] | None:
    """Split a `<symbol>_ENSG\\d+` composite into its parts.

    Returns `(symbol, ensg)` or None if `name` does not match the form.
    Caller decides whether to prefer the symbol or the ENSG portion.
    """
    if not name:
        return None
    m = _SYMBOL_ENSG_RE.match(name)
    if m is None:
        return None
    return m.group(1), m.group(2)
