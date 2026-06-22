"""Helpers for the shared/global, non-dataset inputs that ``load-db`` depends on.

The cross-dataset gene-reference tables — HGNC (``hgnc_complete_set.txt``), MGI
(``MGI_EntrezGene.rpt``), Alliance homology (``HGNC_AllianceHomology.rpt``), … —
live under ``data/homology/`` and are **gitignored**, so a fresh checkout (and a
fresh wrangler laptop) does not have them. When one is missing, ``load-db`` used
to die with a bare ``FileNotFoundError`` on the absolute path, which gives no
hint that the file lives on the servers and is fetched with ``sspsygene
pull-data``. ``require_shared_input`` turns that into an actionable message.
"""

from __future__ import annotations

from pathlib import Path


def require_shared_input(path: Path, *, description: str | None = None) -> Path:
    """Return *path* if it exists, else raise an actionable ``FileNotFoundError``.

    Use this to guard reads of shared/global inputs (homology / cross-species
    mapping files) so a missing file points the wrangler at ``sspsygene
    pull-data`` instead of surfacing a bare, contextless path error.
    """
    if path.exists():
        return path
    what = f"{description} " if description else ""
    raise FileNotFoundError(
        f"Required shared input {what}not found:\n"
        f"    {path}\n\n"
        "This is a shared/global gene-reference input (homology / cross-species "
        "mapping). These files are gitignored and normally live on the SSPsyGene "
        "servers, not in a fresh checkout. Fetch them onto this machine with:\n\n"
        "    sspsygene pull-data\n\n"
        "(See docs/adding-datasets.md / docs/tutorial for the wrangler setup.)"
    )
