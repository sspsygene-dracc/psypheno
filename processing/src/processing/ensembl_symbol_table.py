"""Build the Ensembl-ID to gene-symbol lookup table.

Per Max's 2026-04-28 ask on #75: the website should never display Ensembl
IDs — show the gene symbol whenever one is known. We persist a simple 1:1
mapping table here so the API can post-process result rows server-side.
The table is also a natural artifact for a "download the ENSG↔symbol map"
feature.
"""

import logging
import sqlite3

from processing.central_gene_table import get_central_gene_table

logger = logging.getLogger(__name__)


def compute_ensembl_to_symbol(
    conn: sqlite3.Connection, *, no_index: bool = False
) -> None:
    central_gene_table = get_central_gene_table()
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE ensembl_to_symbol (
            ensembl_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            central_gene_id INTEGER NOT NULL,
            species TEXT NOT NULL
        )"""
    )

    inserted = 0
    skipped = 0
    for entry in central_gene_table.entries:
        if not entry.used:
            continue
        if entry.human_ensembl_gene and entry.human_symbol:
            cur.execute(
                "INSERT OR IGNORE INTO ensembl_to_symbol VALUES (?, ?, ?, ?)",
                (
                    entry.human_ensembl_gene.ensembl_id,
                    entry.human_symbol,
                    entry.row_id,
                    "human",
                ),
            )
            inserted += cur.rowcount or 0
        elif entry.human_ensembl_gene and not entry.human_symbol:
            skipped += 1
        if entry.mouse_ensembl_genes and entry.mouse_symbols:
            # Pick a stable representative mouse symbol — the smallest
            # lexicographically — when an entry has multiple.
            primary_symbol = sorted(entry.mouse_symbols)[0]
            for ensg in entry.mouse_ensembl_genes:
                cur.execute(
                    "INSERT OR IGNORE INTO ensembl_to_symbol VALUES (?, ?, ?, ?)",
                    (ensg.ensembl_id, primary_symbol, entry.row_id, "mouse"),
                )
                inserted += cur.rowcount or 0
    if not no_index:
        cur.execute(
            "CREATE INDEX idx_ensembl_to_symbol_central_gene_id "
            "ON ensembl_to_symbol (central_gene_id)"
        )
    conn.commit()
    logger.info(
        "ensembl_to_symbol: inserted %d mappings (%d ENSG without symbol skipped)",
        inserted,
        skipped,
    )
