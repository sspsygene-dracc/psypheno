"""Per-gene classification flags for the combined-p-values output.

`GeneFlagger` produces the comma-separated `gene_flags` string written to
each output row, drawing on HGNC gene families, a Cis-BP TF list, the NIMH
priority gene list, and missing-HGNC-id detection.
"""

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import click


# HGNC gene_group names mapped to filter flag categories.
# These represent broadly-responsive gene families whose high significance
# in combined p-values typically reflects general perturbation response
# rather than disease-specific signal.
FLAG_GENE_GROUPS: dict[str, list[str]] = {
    "heat_shock": [
        "BAG cochaperones",
        "Chaperonins",
        "DNAJ (HSP40) heat shock proteins",
        "Heat shock 70kDa proteins",
        "Heat shock 90kDa proteins",
        "Small heat shock proteins",
    ],
    "ribosomal": [
        "L ribosomal proteins",
        "S ribosomal proteins",
        "Large subunit mitochondrial ribosomal proteins",
        "Small subunit mitochondrial ribosomal proteins",
        "Mitochondrial ribosomal proteins",
    ],
    "ubiquitin": [
        "Ubiquitin C-terminal hydrolases",
        "Ubiquitin conjugating enzymes E2",
        "Ubiquitin like modifier activating enzymes",
        "Ubiquitin protein ligase E3 component n-recognins",
        "Ubiquitin specific peptidase like",
        "Ubiquitin specific peptidases",
        "Ubiquitins",
    ],
    "mitochondrial_rna": [
        "Mitochondrially encoded long non-coding RNAs",
        "Mitochondrially encoded protein coding genes",
        "Mitochondrially encoded regions",
        "Mitochondrially encoded ribosomal RNAs",
        "Mitochondrially encoded transfer RNAs",
    ],
}

# HGNC locus_group values mapped to filter flag categories.
FLAG_LOCUS_GROUPS: dict[str, list[str]] = {
    "non_coding": ["non-coding RNA"],
    "pseudogene": ["pseudogene"],
}


def _load_tf_list(tf_list_path: Path) -> set[str]:
    """Load HGNC symbols of confirmed transcription factors from CisBP DatabaseExtract CSV."""
    tf_symbols: set[str] = set()
    with open(tf_list_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Is TF?", "").strip() == "Yes":
                symbol = row.get("HGNC symbol", "").strip()
                if symbol:
                    tf_symbols.add(symbol)
    return tf_symbols


def _load_hgnc_gene_flags(
    hgnc_path: Path, tf_symbols: set[str] | None = None
) -> dict[str, str]:
    """Parse HGNC TSV and return {symbol: comma-separated flags} for flagged genes.

    Uses gene_group to match protein family flags (heat_shock, ribosomal, etc.),
    locus_group for broader categories (non_coding), tf_symbols set for
    transcription factors, and locus_type for lncRNAs.
    """
    # Build reverse lookups: group_name -> flag
    group_to_flag: dict[str, str] = {}
    for flag, group_names in FLAG_GENE_GROUPS.items():
        for gn in group_names:
            group_to_flag[gn] = flag

    locus_to_flag: dict[str, str] = {}
    for flag, locus_names in FLAG_LOCUS_GROUPS.items():
        for ln in locus_names:
            locus_to_flag[ln] = flag

    symbol_flags: dict[str, str] = {}
    with open(hgnc_path, "r") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            symbol = row.get("symbol", "").strip()
            if not symbol:
                continue

            flags: set[str] = set()

            # Check gene_group (pipe-separated)
            gene_groups = row.get("gene_group", "")
            if gene_groups:
                for g in gene_groups.split("|"):
                    g = g.strip().strip('"')
                    if g in group_to_flag:
                        flags.add(group_to_flag[g])
            # Check transcription factor list
            if tf_symbols and symbol in tf_symbols:
                flags.add("transcription_factor")

            # Check locus_group
            locus_group = row.get("locus_group", "").strip()
            if locus_group in locus_to_flag:
                flags.add(locus_to_flag[locus_group])

            # Check locus_type for lncRNAs
            locus_type = row.get("locus_type", "").strip()
            if locus_type == "RNA, long non-coding":
                flags.add("lncrna")

            if flags:
                symbol_flags[symbol] = ",".join(sorted(flags))

    return symbol_flags


def _load_nimh_priority_genes(nimh_csv_path: Path) -> set[str]:
    """Load NIMH priority gene symbols from CSV, returning a deduplicated set."""
    symbols: set[str] = set()
    with open(nimh_csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row.get("gene_symbol", "").strip()
            if symbol:
                symbols.add(symbol)
    return symbols


@dataclass
class GeneFlagger:
    """Computes the comma-separated `gene_flags` string for each gene row.

    Combines four sources:
      - HGNC gene_group / locus_group / locus_type families (heat_shock,
        ribosomal, ubiquitin, mitochondrial_rna, non_coding, pseudogene, lncrna)
      - Cis-BP confirmed transcription factors (transcription_factor)
      - NIMH priority gene list (nimh_priority)
      - missing HGNC id (no_hgnc)
    """

    symbol_lookup: dict[int, str]
    hgnc_id_lookup: dict[int, str | None]
    hgnc_flags: dict[str, str]
    nimh_genes: set[str]

    @classmethod
    def from_db(
        cls,
        conn: sqlite3.Connection,
        *,
        hgnc_path: Path | None = None,
        nimh_csv_path: Path | None = None,
        tf_list_path: Path | None = None,
    ) -> "GeneFlagger":
        """Load all reference data and the central_gene lookup tables."""
        tf_symbols: set[str] | None = None
        if tf_list_path and tf_list_path.exists():
            tf_symbols = _load_tf_list(tf_list_path)
            click.echo(f"  Loaded TF list: {len(tf_symbols)} transcription factors")

        hgnc_flags: dict[str, str] = {}
        if hgnc_path and hgnc_path.exists():
            hgnc_flags = _load_hgnc_gene_flags(hgnc_path, tf_symbols=tf_symbols)
            click.echo(f"  Loaded HGNC gene flags for {len(hgnc_flags)} genes")

        nimh_genes: set[str] = set()
        if nimh_csv_path and nimh_csv_path.exists():
            nimh_genes = _load_nimh_priority_genes(nimh_csv_path)
            click.echo(
                f"  Loaded NIMH priority gene list: {len(nimh_genes)} unique genes"
            )

        symbol_lookup: dict[int, str] = {}
        hgnc_id_lookup: dict[int, str | None] = {}
        rows = conn.execute(
            "SELECT id, human_symbol, hgnc_id FROM central_gene "
            "WHERE human_symbol IS NOT NULL"
        ).fetchall()
        for row in rows:
            symbol_lookup[row[0]] = row[1]
            hgnc_id_lookup[row[0]] = row[2]

        return cls(
            symbol_lookup=symbol_lookup,
            hgnc_id_lookup=hgnc_id_lookup,
            hgnc_flags=hgnc_flags,
            nimh_genes=nimh_genes,
        )

    def flags_for(self, gene_id: int) -> str | None:
        """Return comma-separated, sorted flag string, or None if no flags apply."""
        flags: set[str] = set()
        symbol = self.symbol_lookup.get(gene_id)
        if symbol and self.hgnc_flags:
            flag_str = self.hgnc_flags.get(symbol)
            if flag_str:
                flags.update(flag_str.split(","))
        hgnc_id = self.hgnc_id_lookup.get(gene_id)
        if not hgnc_id:
            flags.add("no_hgnc")
        if symbol and symbol in self.nimh_genes:
            flags.add("nimh_priority")
        return ",".join(sorted(flags)) if flags else None
