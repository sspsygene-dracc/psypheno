"""Download and parse RefSeq GenBank data for human gene descriptions.

Downloads the GRCh38 latest_rna.gbff.gz from NCBI RefSeq, then uses BioPython
to extract gene summaries keyed by Entrez Gene ID.

Two-stage workflow:
1. `build_descriptions_db()` (CLI: `sspsygene load-gene-descriptions`) parses
   the GenBank file into a standalone SQLite file (gene_descriptions.db).
2. During `load-db`, `copy_gene_descriptions()` ATTACHes that file and copies
   only the rows matching genes present in the central_gene table.
"""

import gzip
import sqlite3
import urllib.request
from pathlib import Path
from typing import Any

import click
from Bio import SeqIO


_GBFF_URL = (
    "https://ftp.ncbi.nlm.nih.gov/refseq/H_sapiens/annotation/"
    "GRCh38_latest/refseq_identifiers/GRCh38_latest_rna.gbff.gz"
)


def _download_progress(block_num: int, block_size: int, total_size: int) -> None:
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        mb = downloaded / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        click.echo(f"\r  Downloaded {mb:.0f} / {total_mb:.0f} MB ({pct}%)", nl=False)
    else:
        mb = downloaded / (1024 * 1024)
        click.echo(f"\r  Downloaded {mb:.0f} MB", nl=False)


def _parse_summary(record: Any) -> str | None:
    """Extract the Summary section from a GenBank record's comment."""
    comment = record.annotations.get("comment", None)
    if not comment:
        return None
    assert isinstance(comment, str)
    rv = None
    for section in comment.split("\n"):
        if section.startswith("Summary:"):
            rv = section[len("Summary:"):].strip().replace("\n", " ")
        elif rv is not None:
            rv += " " + section.strip()
            if section.endswith("]."):
                break
    return rv


def _parse_entrez_gene_id(record: Any) -> int | None:
    """Extract Entrez Gene ID from a GenBank record's gene feature db_xref."""
    for feature in record.features:
        if feature.type != "gene":
            continue
        for db_xref in feature.qualifiers.get("db_xref", []):
            if db_xref.startswith("GeneID:"):
                try:
                    return int(db_xref.split(":")[1])
                except ValueError:
                    pass
    return None


def build_descriptions_db(data_dir: Path) -> Path:
    """Parse RefSeq GenBank file and write a standalone gene_descriptions.db.

    The DB contains a single table:
        gene_descriptions_source(entrez_gene_id INTEGER PRIMARY KEY, description TEXT)

    Returns the path to the created DB file.
    """
    gbff_path = data_dir / "homology" / "GRCh38_latest_rna.gbff.gz"
    if not gbff_path.exists():
        gbff_path.parent.mkdir(parents=True, exist_ok=True)
        click.echo(f"  Downloading {_GBFF_URL}...")
        urllib.request.urlretrieve(_GBFF_URL, gbff_path, reporthook=_download_progress)
        click.echo("")

    db_path = data_dir / "db" / "gene_descriptions.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE gene_descriptions_source "
        "(entrez_gene_id INTEGER PRIMARY KEY, description TEXT)"
    )

    count = 0
    seen_entrez: set[int] = set()
    click.echo("  Parsing RefSeq GenBank file (this may take a few minutes)...")
    with gzip.open(gbff_path, "rt") as f:
        for record in SeqIO.parse(f, "genbank"):  # type: ignore[attr-defined]
            entrez_id = _parse_entrez_gene_id(record)
            if entrez_id is None or entrez_id in seen_entrez:
                continue
            summary = _parse_summary(record)
            if not summary:
                continue
            seen_entrez.add(entrez_id)
            conn.execute(
                "INSERT OR IGNORE INTO gene_descriptions_source VALUES (?, ?)",
                (entrez_id, summary),
            )
            count += 1
            if count % 1000 == 0:
                click.echo(f"\r  Parsed {count} gene summaries...", nl=False)

    conn.commit()
    conn.close()
    click.echo(f"\n  Wrote {count} human gene descriptions to {db_path}")
    return db_path


def copy_gene_descriptions(
    conn: sqlite3.Connection,
    data_dir: Path,
    *,
    no_index: bool = False,
) -> None:
    """Copy gene descriptions from standalone DB into the main DB.

    Only copies rows for genes that exist in the central_gene table.
    Skips gracefully if gene_descriptions.db doesn't exist.
    """
    desc_db_path = data_dir / "db" / "gene_descriptions.db"
    if not desc_db_path.exists():
        click.echo(
            "\n  No gene_descriptions.db found. "
            "Run 'sspsygene load-gene-descriptions' first. Skipping."
        )
        return

    click.echo("\nCopying gene descriptions...")
    conn.execute(f"ATTACH DATABASE '{desc_db_path}' AS desc_db")
    conn.execute(
        "CREATE TABLE gene_descriptions "
        "(central_gene_id INTEGER PRIMARY KEY, description TEXT)"
    )
    conn.execute(
        "INSERT INTO gene_descriptions (central_gene_id, description) "
        "SELECT cg.id, gd.description "
        "FROM central_gene cg "
        "JOIN desc_db.gene_descriptions_source gd "
        "  ON gd.entrez_gene_id = cg.human_entrez_gene "
        "WHERE cg.human_entrez_gene IS NOT NULL"
    )
    count = conn.execute("SELECT COUNT(*) FROM gene_descriptions").fetchone()[0]
    if not no_index:
        conn.execute(
            "CREATE INDEX gene_descriptions_idx "
            "ON gene_descriptions (central_gene_id)"
        )
    conn.commit()
    conn.execute("DETACH DATABASE desc_db")
    click.echo(f"  Copied descriptions for {click.style(str(count), bold=True)} genes")
