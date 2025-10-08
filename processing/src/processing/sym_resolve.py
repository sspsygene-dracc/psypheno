from collections import defaultdict
import csv
from pathlib import Path

from processing.types.entrez_gene_map import EntrezGeneMap
from processing.my_logger import get_sspsygene_logger
from processing.types.entrez_gene import EntrezGene
from processing.types.entrez_gene_entry import EntrezGeneEntry


def parse_hgnc(fname: Path) -> EntrezGeneMap:
    rv: list[EntrezGeneEntry] = []
    total = 0
    no_entrez_id = 0
    rows: list[dict[str, str]] = []
    with open(fname, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)

    def get_entrez_id(row: dict[str, str]) -> int:
        entrez_id_str = row["entrez_id"]
        if entrez_id_str == "":
            get_sspsygene_logger().debug("HGNC: No entrez id for %s", symbol)
            entrez_id = -1
        else:
            entrez_id = int(entrez_id_str)
        return entrez_id

    symbols: set[str] = set()
    for row in rows:
        total += 1
        symbol = row["symbol"]
        entrez_id = get_entrez_id(row)
        if entrez_id == -1:
            no_entrez_id += 1
        assert symbol not in symbols
        rv.append(EntrezGeneEntry(symbol, True, EntrezGene(entrez_id)))

    rv_prev_symbols: dict[str, set[EntrezGene]] = defaultdict(set)
    for row in rows:
        prev_symbols = row["prev_symbol"].split("|")
        if not prev_symbols:
            continue
        entrez_id = get_entrez_id(row)
        for prev_symbol in prev_symbols:
            if prev_symbol in symbols:
                get_sspsygene_logger().debug(
                    "Symbol %s is also a symbol",
                    prev_symbol,
                )
                continue
            rv_prev_symbols[prev_symbol].add(EntrezGene(entrez_id))
    rv_prev_symbols = {x: y for x, y in rv_prev_symbols.items() if len(y) == 1}
    for prev_symbol, entrez_genes in rv_prev_symbols.items():
        assert len(entrez_genes) == 1
        entrez_gene = list(entrez_genes)[0]
        rv.append(EntrezGeneEntry(prev_symbol, False, entrez_gene))

    get_sspsygene_logger().info(
        "HGNC: Total: %d, No entrez id: %d (%.2f%%)",
        total,
        no_entrez_id,
        no_entrez_id / total * 100,
    )
    return EntrezGeneMap(rv)


mgi_entrez_header = [
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


def parse_mgi(fname: Path) -> EntrezGeneMap:
    total = 0
    no_entrez_id = 0

    rows: list[dict[str, str]] = []
    withdrawn_map: dict[str, set[str]] = defaultdict(set)

    with open(fname, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t", fieldnames=mgi_entrez_header)
        for row in reader:
            status = row["Status"]
            assert status in {"O", "W"}
            if status == "W":
                marker_name = row["Marker Name"]
                if " = " in marker_name:
                    symbol = marker_name.split("=")[1].strip()
                    # we currently don't do anything with this:
                    withdrawn_map[symbol].add(row["Marker Symbol"])
                    get_sspsygene_logger().debug(
                        "Adding other id %s for %s",
                        row["Marker Symbol"],
                        symbol,
                    )
                continue
            elem_type = row["Type"]
            assert elem_type in {
                "Complex/Cluster/Region",
                "BAC/YAC end",
                "Cytogenetic Marker",
                "QTL",
                "Transgene",
                "Pseudogene",
                "DNA Segment",
                "Gene",
                "Other Genome Feature",
            }
            if elem_type not in ("Gene", "Pseudogene"):
                # these are not listed with entrez ids
                continue
            rows.append(row)
            total += 1

    def get_entrez_id(row: dict[str, str]) -> int:
        entrez_id_str = row["Entrez Gene ID"]
        if entrez_id_str == "" or entrez_id_str == "null":
            get_sspsygene_logger().debug("MGI: No entrez id for %s", symbol)
            entrez_id = -1
        else:
            entrez_id = int(entrez_id_str)
        return entrez_id

    symbols: set[str] = set()
    rv: list[EntrezGeneEntry] = []
    for row in rows:
        symbol = row["Marker Symbol"]
        assert symbol not in symbols, f"Symbol {symbol} is already known"
        symbols.add(symbol)
        entrez_id = get_entrez_id(row)
        if entrez_id == -1:
            no_entrez_id += 1
        rv.append(EntrezGeneEntry(symbol, True, EntrezGene(entrez_id)))

    rv_synonyms: dict[str, set[EntrezGene]] = defaultdict(set)
    for row in rows:
        synonyms = [x for x in row["Synonyms"].split("|") if x != ""]
        entrez_id = get_entrez_id(row)
        for synonym in synonyms:
            if synonym in symbols:
                get_sspsygene_logger().debug(
                    "Symbol %s is also a symbol",
                    synonym,
                )
                continue
            rv_synonyms[synonym].add(EntrezGene(entrez_id))

    symbol_map: dict[str, set[EntrezGene]] = defaultdict(set)
    for symbol in rv:
        symbol_map[symbol.name].add(symbol.entrez_id)
    for entrez_ids in symbol_map.values():
        assert len(entrez_ids) == 1

    for symbol, other_ids in withdrawn_map.items():
        for other_id in other_ids:
            if (
                other_id not in symbols
                and other_id not in rv_synonyms
                and symbol in symbols
            ):
                get_sspsygene_logger().debug(
                    "Adding other id %s (%s) to map for %s",
                    other_id,
                    symbol_map[symbol],
                    symbol,
                )
                rv_synonyms[other_id].update(symbol_map[symbol])

    for synonym, entrez_genes in rv_synonyms.items():
        if len(entrez_genes) != 1:
            continue
        entrez_gene = list(entrez_genes)[0]
        rv.append(EntrezGeneEntry(synonym, False, entrez_gene))

    get_sspsygene_logger().info(
        "MGI: Total: %d, No entrez id: %d (%.2f%%)",
        total,
        no_entrez_id,
        no_entrez_id / total * 100,
    )
    return EntrezGeneMap(rv)


zfin_header = [
    "ZFIN ID",
    "ZFIN Symbol",
    "ZFIN Name",
    "Human Symbol",
    "Human Name",
    "OMIM ID",
    "Gene ID",
    "HGNC ID",
    "Evidence",
    "Pub ID",
    "ZFIN Abbreviation Name",
    "ECO ID",
    "ECO Term Name",
]


def parse_zfin(fname: Path) -> EntrezGeneMap:
    rv: list[EntrezGeneEntry] = []
    total = 0
    no_entrez_id = 0
    with open(fname, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t", fieldnames=zfin_header)
        for row in reader:
            total += 1
            symbol = row["ZFIN Symbol"]
            entrez_id = int(row["Gene ID"])
            if entrez_id == 0:
                get_sspsygene_logger().debug("ZFIN: No entrez id for %s", symbol)
                no_entrez_id += 1
                entrez_id = -1
            rv.append(EntrezGeneEntry(symbol, True, EntrezGene(entrez_id)))
    get_sspsygene_logger().info(
        "ZFIN: Total: %d, No entrez id: %d (%.2f%%)",
        total,
        no_entrez_id,
        no_entrez_id / total * 100,
    )
    return EntrezGeneMap(rv)
