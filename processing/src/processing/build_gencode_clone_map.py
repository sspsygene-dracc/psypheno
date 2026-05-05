"""Build data/homology/gencode_clone_map.tsv from a pinned GENCODE GTF.

This is a one-time wrangler script — output TSV gets committed to git;
the GTF input stays gitignored. Re-run only when bumping the GENCODE
release or when HGNC adds new ensembl_gene_id mappings.

GENCODE release pinning: v38 (Ensembl 104, May 2021).

Why v38: most legacy clone names (RP11-…, CTD-…, KB-…, …) were still
present as `gene_name` in v38; later releases (v45+) dropped or renamed
many of them. Coverage on the polygenic-risk-20 dataset (~5,097 unique
clones) is the empirical justification for this pin — see #139.

Inputs (under SSPSYGENE_DATA_DIR):
  - homology/hgnc_complete_set.txt                       (existing artifact)
  - homology/gencode.v38.long_noncoding_RNAs.gtf.gz      (downloaded by BUILD)
  - homology/gencode.v38.basic.annotation.gtf.gz         (downloaded by BUILD)

Both GTFs are parsed; unique clone names are unioned. The lncRNA-only
GTF is small and covers most legacy lncRNA placeholders (RP11-…, CTD-…
that are still annotated as lncRNAs in v38). The basic-annotation GTF
adds the protein-coding and pseudogene loci that share the same naming
scheme. Coverage on polygenic-risk-20/Supp_1_all.csv jumps from ~50%
(lncRNA-only) to a much higher fraction with both included — see #139
for the empirical justification.

Output:
  - homology/gencode_clone_map.tsv

TSV columns: clone_name<TAB>resolution<TAB>kind
Where `kind` is one of:
  - hgnc_symbol           (resolution = current HGNC symbol)
  - current_ensg          (resolution = stable ENSG anchor)
  - current_ac_accession  (resolution = AC/AL/AP accession)

The fourth #139 kind, `retired`, is intentionally not produced — see
the GencodeCloneIndex docstring.
"""

from __future__ import annotations

import csv
import gzip
import os
import re
from pathlib import Path

from processing.preprocessing.helpers import _GENCODE_CLONE_RE


# Lines where the value should be classified as `current_ac_accession`
# rather than left as a clone — these are gene_names that were already
# renamed to a contig-style accession in v38.
_AC_ACCESSION_RE = re.compile(r"^(AC|AL|AP)\d{6,8}\.\d+$")

# GTF attribute parser: simple key "value" pairs separated by `; `.
_GTF_ATTR_RE = re.compile(r'(\w+) "([^"]*)"')


def _parse_attributes(attrs_field: str) -> dict[str, str]:
    return dict(_GTF_ATTR_RE.findall(attrs_field))


def _strip_ensg_version(ensg: str) -> str:
    return ensg.split(".", 1)[0] if "." in ensg else ensg


def _load_hgnc_ensg_to_symbol(hgnc_file: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(hgnc_file, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            symbol = (row.get("symbol") or "").strip()
            ensg = (row.get("ensembl_gene_id") or "").strip()
            if not symbol or not ensg or ensg == "null":
                continue
            out[ensg] = symbol
    return out


def _iter_gtf_genes(gtf_path: Path):
    """Yield (gene_id_bare, gene_name) for each `gene` feature in the GTF."""
    with gzip.open(gtf_path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 9 or cols[2] != "gene":
                continue
            attrs = _parse_attributes(cols[8])
            ensg = attrs.get("gene_id", "")
            name = attrs.get("gene_name", "")
            if not ensg or not name:
                continue
            yield _strip_ensg_version(ensg), name


def build_clone_map(
    *,
    gtf_paths: list[Path],
    hgnc_file: Path,
    out_path: Path,
) -> dict[str, int]:
    """Parse one-or-more GTFs + HGNC dump and write the clone map TSV.

    Returns a per-kind row-count dict for the build summary. The GTFs
    are unioned by clone_name; the first GTF wins on duplicates (the
    lncRNA-only GTF is intentionally listed first so its annotations
    take precedence over the basic-annotation GTF where they overlap,
    because lncRNA assignments are the more specific call).
    """
    hgnc_ensg_to_symbol = _load_hgnc_ensg_to_symbol(hgnc_file)

    rows: list[tuple[str, str, str]] = []
    counts = {"hgnc_symbol": 0, "current_ensg": 0, "current_ac_accession": 0}
    seen: set[str] = set()

    for gtf_path in gtf_paths:
        for ensg, name in _iter_gtf_genes(gtf_path):
            if name in seen:
                continue
            is_clone = bool(_GENCODE_CLONE_RE.match(name))
            is_ac = bool(_AC_ACCESSION_RE.match(name))
            if not (is_clone or is_ac):
                continue
            seen.add(name)
            # HGNC-symbol lookup applies to both clone-shaped and
            # AC-shaped gene_names: HGNC sometimes promotes a locus to a
            # symbol after the pinned GENCODE release, in which case the
            # GTF still carries the older AC name. Without this lookup
            # we'd miss ~15% of AC-shaped loci that have a current
            # symbol.
            symbol = hgnc_ensg_to_symbol.get(ensg)
            if symbol is not None:
                rows.append((name, symbol, "hgnc_symbol"))
                counts["hgnc_symbol"] += 1
            elif is_ac:
                # No HGNC symbol; the AC accession itself is the
                # canonical name we'll surface.
                rows.append((name, name, "current_ac_accession"))
                counts["current_ac_accession"] += 1
            else:
                # Clone-shaped, no symbol; ENSG is the stable anchor.
                rows.append((name, ensg, "current_ensg"))
                counts["current_ensg"] += 1

    rows.sort(key=lambda r: r[0])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(["clone_name", "resolution", "kind"])
        writer.writerows(rows)
    return counts


def main() -> None:
    try:
        data_dir = Path(os.environ["SSPSYGENE_DATA_DIR"])
    except KeyError as e:
        raise SystemExit(
            "SSPSYGENE_DATA_DIR is not set; export it to point at the data "
            "directory containing homology/hgnc_complete_set.txt and "
            "homology/gencode.v38.long_noncoding_RNAs.gtf.gz."
        ) from e

    gtf_paths = [
        # Order matters: lncRNA-only first (more specific annotation),
        # basic-annotation second (covers protein-coding + pseudogene
        # loci sharing the same naming scheme).
        data_dir / "homology" / "gencode.v38.long_noncoding_RNAs.gtf.gz",
        data_dir / "homology" / "gencode.v38.basic.annotation.gtf.gz",
    ]
    hgnc_file = data_dir / "homology" / "hgnc_complete_set.txt"
    out_path = data_dir / "homology" / "gencode_clone_map.tsv"

    for p in gtf_paths:
        if not p.exists():
            raise SystemExit(
                f"Missing GTF input: {p}\n"
                "Run `cd data/homology && bash BUILD` first."
            )
    if not hgnc_file.exists():
        raise SystemExit(
            f"Missing HGNC input: {hgnc_file}\n"
            "Run `cd data/homology && bash BUILD` first."
        )

    counts = build_clone_map(
        gtf_paths=gtf_paths, hgnc_file=hgnc_file, out_path=out_path
    )
    total = sum(counts.values())
    print(f"Wrote {out_path}")
    print(f"  total: {total}")
    for kind, n in counts.items():
        print(f"  {kind}: {n}")


if __name__ == "__main__":
    main()
