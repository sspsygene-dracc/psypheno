#!/usr/bin/env python3
"""Build data/ontology/uberon_terms.tsv from an UBERON basic.obo release.

The TSV is the vendored term list dataset `anatomy:` tags are validated
against, and the is_a/part_of ancestor closure the web region filter uses to
match a term to its subregions (picking "cerebral cortex" also finds datasets
tagged "neocortex" or a Brodmann area).

Selection rule (keeps the committed file small):
  1. every non-obsolete UBERON term that is a descendant, via is_a / part_of
     (transitively, in any mix), of UBERON:0001016 "nervous system" — this
     covers brain, spinal cord, every cortical / nuclear / Brodmann-area term,
     retina, peripheral nerves, ...;
  2. plus the handful of whole-organism / organ terms in EXTRA_TERMS (for
     whole-larva datasets, cell lines from non-neural tissue, ...);
  3. plus every is_a / part_of ancestor of the terms above, so each listed
     term's ancestor set is closed within the file.

Columns: id, label, ancestors (comma-separated UBERON ids, the full transitive
is_a/part_of ancestor set of the term, excluding the term itself; sorted).

Usage (see makeDoc.txt for the download):
    python3 build_uberon_terms.py uberon-basic.obo uberon_terms.tsv
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

NERVOUS_SYSTEM = "UBERON:0001016"

# Non-neural terms a dataset may plausibly be tagged with. Extend this list (and
# re-run the script) when a dataset needs another organ; never hand-edit the TSV.
EXTRA_TERMS = [
    "UBERON:0000468",  # multicellular organism (whole animal / larva)
    "UBERON:0000922",  # embryo
    "UBERON:0000033",  # head
    "UBERON:0001851",  # cortex (generic organ cortex)
    "UBERON:0002113",  # kidney (HEK293T)
    "UBERON:0002107",  # liver
    "UBERON:0002048",  # lung
    "UBERON:0000948",  # heart
    "UBERON:0000178",  # blood
    "UBERON:0002371",  # bone marrow
    "UBERON:0002097",  # skin of body
    "UBERON:0000970",  # eye
    "UBERON:0001264",  # pancreas
    "UBERON:0000160",  # intestine
    "UBERON:0000473",  # testis
    "UBERON:0000992",  # ovary
    "UBERON:0001013",  # adipose tissue
    "UBERON:0002385",  # muscle tissue
]


def parse_obo(path: Path) -> tuple[dict[str, str], dict[str, set[str]], str]:
    """Return (id -> label, id -> direct is_a/part_of parents, data-version)."""
    labels: dict[str, str] = {}
    parents: dict[str, set[str]] = defaultdict(set)
    data_version = ""
    stanza: str | None = None
    cur_id: str | None = None
    cur_name: str | None = None
    cur_parents: set[str] = set()
    obsolete = False

    def flush() -> None:
        if stanza == "Term" and cur_id and cur_id.startswith("UBERON:") and not obsolete:
            labels[cur_id] = cur_name or ""
            parents[cur_id] |= {p for p in cur_parents if p.startswith("UBERON:")}

    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("["):
                flush()
                stanza = line.strip("[]")
                cur_id, cur_name, cur_parents, obsolete = None, None, set(), False
                continue
            if stanza is None:
                if line.startswith("data-version:"):
                    data_version = line.split(":", 1)[1].strip()
                continue
            if stanza != "Term":
                continue
            key, _, value = line.partition(": ")
            if key == "id":
                cur_id = value.strip()
            elif key == "name":
                cur_name = value.strip()
            elif key == "is_obsolete" and value.strip() == "true":
                obsolete = True
            elif key == "is_a":
                cur_parents.add(value.split()[0])
            elif key == "relationship":
                rel, _, rest = value.partition(" ")
                if rel == "part_of":
                    cur_parents.add(rest.split()[0])
        flush()
    # Drop edges to terms that are not (non-obsolete) UBERON terms.
    for term, ps in parents.items():
        parents[term] = {p for p in ps if p in labels}
    return labels, dict(parents), data_version


def ancestor_closure(parents: dict[str, set[str]]) -> dict[str, set[str]]:
    memo: dict[str, set[str]] = {}

    def visit(term: str, stack: set[str]) -> set[str]:
        if term in memo:
            return memo[term]
        out: set[str] = set()
        stack.add(term)
        for p in parents.get(term, ()):
            if p in stack:  # defensive: UBERON is acyclic over is_a/part_of
                continue
            out.add(p)
            out |= visit(p, stack)
        stack.discard(term)
        memo[term] = out
        return out

    sys.setrecursionlimit(100_000)
    for term in parents:
        visit(term, set())
    return memo


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    obo_path, out_path = Path(argv[1]), Path(argv[2])
    labels, parents, data_version = parse_obo(obo_path)
    ancestors = ancestor_closure(parents)

    missing = [t for t in [NERVOUS_SYSTEM, *EXTRA_TERMS] if t not in labels]
    if missing:
        print(f"terms not found in {obo_path}: {missing}", file=sys.stderr)
        return 1

    selected = {t for t, anc in ancestors.items() if NERVOUS_SYSTEM in anc}
    selected.add(NERVOUS_SYSTEM)
    selected |= set(EXTRA_TERMS)
    for t in list(selected):
        selected |= ancestors[t]

    with open(out_path, "w", encoding="utf-8") as out:
        out.write(f"# UBERON subset built from {data_version} by build_uberon_terms.py\n")
        out.write("id\tlabel\tancestors\n")
        for t in sorted(selected):
            label = labels[t].replace("\t", " ")
            out.write(f"{t}\t{label}\t{','.join(sorted(ancestors[t]))}\n")
    print(f"wrote {len(selected)} terms to {out_path} ({data_version})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
