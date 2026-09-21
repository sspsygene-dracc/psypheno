"""Genes that exist in GENCODE / NCBI but have no HGNC symbol (#113 follow-up).

Roughly 95k of the values our datasets carry are real loci that HGNC has never
named: unnamed Ensembl lncRNAs (`AC010729.2`, bare `ENSG…`), NCBI `LOC…`
placeholders, RefSeq functional elements. Before this module each of them
became a `manually_added=1` stub — one per dataset value, with no cross-dataset
identity and an ID that depended on the order datasets happened to load in.

Here they get a *reference* identity instead, read from the same files the rest
of the gene table is built from:

  * `gencode.v38.*.gtf.gz` — every gene whose ENSG HGNC doesn't list.
  * `Homo_sapiens.gene_info.gz` — every NCBI gene whose GeneID / HGNC xref
    HGNC doesn't list. When its Ensembl xref names a GENCODE locus we already
    have, the two merge into one locus rather than two.

A locus is keyed by its stable identifier (`ensg:ENSG…` / `entrez:…`), which is
what makes its central_gene ID survive a rebuild — see `stable_row_id`.

Both inputs are optional: without them (a fresh checkout that hasn't run
`sspsygene pull-data`) the index is empty and unnamed loci fall back to stubs,
exactly as before.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Reference and stub IDs are hashes, not positions, so they survive a rebuild.
# They live above the positional HGNC/MGI IDs (~700k today).
#
# The space is far larger than it needs to be on purpose: a collision has to be
# broken by probing, and probing depends on the order entries are created —
# exactly the build-order dependence this module exists to remove. At 2**45 a
# build with 1e5 hashed IDs collides with probability ~1e-4, against ~2 per
# build at 2**31. Both bounds stay well inside float64's exact-integer range
# (2**53), which is what JSON / JS on the web side can carry losslessly.
STABLE_ID_BASE = 1_000_000_000_000
STABLE_ID_SPACE = 2**45

_GENE_ID_RE = re.compile(r'gene_id "([^".]+)')
_GENE_NAME_RE = re.compile(r'gene_name "([^"]+)"')
_GENE_TYPE_RE = re.compile(r'gene_type "([^"]+)"')


def stable_row_id(key: str) -> int:
    """Deterministic central_gene ID for a stable key (`ensg:…`, `stub:…`).

    Same key, same ID — in this build, the next one, and on every instance,
    which is what the meta / overview DBs need: they store central_gene IDs and
    are rebuilt on a different cadence than the dataset DB.
    """
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return STABLE_ID_BASE + int.from_bytes(digest, "big") % STABLE_ID_SPACE


@dataclass(slots=True)
class ReferenceLocus:
    """A real locus with no HGNC symbol, as named by GENCODE and/or NCBI."""

    key: str
    display: str
    ensembl_id: str | None = None
    entrez_id: int | None = None
    names: set[str] = field(default_factory=set)

    @property
    def row_id(self) -> int:
        return stable_row_id(self.key)


@dataclass
class ReferenceLociIndex:
    """Name → locus lookup for values HGNC/MGI can't resolve.

    `by_name` only holds names that are unambiguous: a name already resolvable
    through HGNC/MGI never enters (the existing entry wins), and a name two
    loci both claim is dropped rather than guessed at — linking a row to two
    genes is worse than leaving it a stub.
    """

    by_name: dict[str, ReferenceLocus] = field(default_factory=dict)

    def get(self, name: str) -> ReferenceLocus | None:
        return self.by_name.get(name)

    def __len__(self) -> int:
        return len(self.by_name)


def _parse_gencode(
    paths: list[Path], hgnc_ensembl_ids: set[str]
) -> dict[str, ReferenceLocus]:
    loci: dict[str, ReferenceLocus] = {}
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                # Cheap pre-filter: the feature type is the third column and
                # gene lines are ~4% of a GTF.
                fields = line.split("\t", 3)
                if len(fields) < 3 or fields[2] != "gene":
                    continue
                gene_id = _GENE_ID_RE.search(line)
                if gene_id is None:
                    continue
                ensg = gene_id.group(1)
                if ensg in hgnc_ensembl_ids or ensg in loci:
                    continue
                name_match = _GENE_NAME_RE.search(line)
                name = name_match.group(1) if name_match else ensg
                locus = ReferenceLocus(
                    key=f"ensg:{ensg}", display=name, ensembl_id=ensg
                )
                locus.names.update({name, ensg})
                loci[ensg] = locus
    return loci


def _split_xrefs(raw: str) -> dict[str, str]:
    """`MIM:138670|HGNC:HGNC:5|Ensembl:ENSG00000121410` → {'HGNC': 'HGNC:5', …}."""
    out: dict[str, str] = {}
    if not raw or raw == "-":
        return out
    for xref in raw.split("|"):
        source, sep, value = xref.partition(":")
        if sep and value:
            out.setdefault(source, value)
    return out


def _parse_ncbi(
    path: Path,
    hgnc_ids: set[str],
    hgnc_entrez_ids: set[int],
    by_ensg: dict[str, ReferenceLocus],
) -> list[ReferenceLocus]:
    """NCBI genes HGNC doesn't list, merged into `by_ensg` where they overlap."""
    extra: list[ReferenceLocus] = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = f.readline().lstrip("#").rstrip("\n").split("\t")
        col = {name: i for i, name in enumerate(header)}
        for line in f:
            row = line.rstrip("\n").split("\t")
            if row[col["tax_id"]] != "9606":
                continue
            try:
                gene_id = int(row[col["GeneID"]])
            except (ValueError, IndexError):
                continue
            if gene_id in hgnc_entrez_ids:
                continue
            xrefs = _split_xrefs(row[col["dbXrefs"]])
            if xrefs.get("HGNC") in hgnc_ids:
                continue
            symbol = row[col["Symbol"]]
            if not symbol or symbol == "-":
                continue
            ensg = xrefs.get("Ensembl")
            locus = by_ensg.get(ensg) if ensg else None
            if locus is not None:
                # Same locus under two catalogues: keep GENCODE's display name
                # (the ENSG is the key), add the NCBI symbol as another way in.
                locus.entrez_id = gene_id
                locus.names.add(symbol)
                continue
            locus = ReferenceLocus(
                key=f"entrez:{gene_id}",
                display=symbol,
                ensembl_id=ensg,
                entrez_id=gene_id,
            )
            locus.names.add(symbol)
            if ensg:
                locus.names.add(ensg)
            extra.append(locus)
    return extra


def build_reference_loci_index(
    *,
    gencode_paths: list[Path],
    ncbi_gene_info_path: Path | None,
    hgnc_ensembl_ids: set[str],
    hgnc_ids: set[str],
    hgnc_entrez_ids: set[int],
    claimed_names: set[str],
) -> ReferenceLociIndex:
    """Build the name → locus index. Missing inputs are skipped, not fatal."""
    present = [p for p in gencode_paths if p.exists()]
    for path in gencode_paths:
        if not path.exists():
            logger.warning(
                "reference loci: %s not found — unnamed Ensembl loci will fall "
                "back to per-dataset stubs (run `sspsygene pull-data`)",
                path,
            )
    by_ensg = _parse_gencode(present, hgnc_ensembl_ids) if present else {}

    extra: list[ReferenceLocus] = []
    if ncbi_gene_info_path is not None and ncbi_gene_info_path.exists():
        extra = _parse_ncbi(ncbi_gene_info_path, hgnc_ids, hgnc_entrez_ids, by_ensg)
    elif ncbi_gene_info_path is not None:
        logger.warning(
            "reference loci: %s not found — NCBI-only loci (LOC…) will fall "
            "back to per-dataset stubs (run `sspsygene pull-data`)",
            ncbi_gene_info_path,
        )

    by_name: dict[str, ReferenceLocus] = {}
    ambiguous: set[str] = set()
    all_loci = list(by_ensg.values()) + extra

    # A display name has to identify one gene. Two kinds of clash:
    #   * HGNC already uses it for a different gene (NCBI calls GeneID
    #     105373170 `DISC2`; HGNC gives DISC2 to another locus);
    #   * several reference loci share it (GENCODE names six rRNA genes
    #     `5_8S_rRNA`).
    # Either way, fall back down the identifier preference — HGNC symbol >
    # ENSG > accession (CLAUDE.md) — to the ENSG, or to the GeneID when the
    # locus has no ENSG. A shared name is still never a *lookup* key, so no
    # row is linked to a guessed gene; this only decides what is displayed.
    display_counts: Counter[str] = Counter(locus.display for locus in all_loci)
    renamed = 0
    for locus in all_loci:
        if locus.display in claimed_names or display_counts[locus.display] > 1:
            if locus.ensembl_id:
                locus.display = locus.ensembl_id
            elif locus.entrez_id is not None:
                locus.display = f"GeneID:{locus.entrez_id}"
            else:
                continue
            renamed += 1

    for locus in all_loci:
        for name in locus.names:
            if not name or name in claimed_names or name in ambiguous:
                continue
            existing = by_name.get(name)
            if existing is None:
                by_name[name] = locus
            elif existing.key != locus.key:
                # Two loci claim the name — drop it rather than pick one.
                del by_name[name]
                ambiguous.add(name)
    logger.info(
        "reference loci: %d loci (%d from GENCODE, %d NCBI-only), %d names "
        "indexed, %d ambiguous names dropped, %d displayed by ENSG / GeneID "
        "because their catalogue name identifies more than one gene",
        len(all_loci),
        len(by_ensg),
        len(extra),
        len(by_name),
        len(ambiguous),
        renamed,
    )
    return ReferenceLociIndex(by_name=by_name)
