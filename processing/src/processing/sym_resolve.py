from collections import defaultdict
import csv
from dataclasses import dataclass
from pathlib import Path

from processing.types.entrez_gene_map import EntrezGeneMap
from processing.my_logger import get_sspsygene_logger
from processing.types.entrez_gene import EntrezGene
from processing.types.entrez_gene_entry import EntrezGeneEntry


@dataclass
class ParseHGNCResult:
    entrez_gene_map: EntrezGeneMap
    hgnc_id_to_human_entrez_id: dict[str, EntrezGene]


def parse_hgnc(fname: Path) -> ParseHGNCResult:
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

    rv_hgnc_id_to_human_entrez_id: dict[str, EntrezGene] = {}
    rv_prev_symbols: dict[str, set[EntrezGene]] = defaultdict(set)
    for row in rows:
        prev_symbols = row["prev_symbol"].split("|")
        if not prev_symbols:
            continue
        entrez_id = get_entrez_id(row)
        hgnc_id = row["hgnc_id"]
        if entrez_id >= 0:
            assert hgnc_id not in rv_hgnc_id_to_human_entrez_id
            rv_hgnc_id_to_human_entrez_id[hgnc_id] = EntrezGene(entrez_id)
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
    return ParseHGNCResult(EntrezGeneMap(rv), rv_hgnc_id_to_human_entrez_id)


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


def parse_mgi_entrez_to_hgnc(
    alliance_homology_fname: Path,
) -> dict[EntrezGene, set[str]]:
    rv: dict[EntrezGene, set[str]] = defaultdict(set)
    with open(alliance_homology_fname, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            entrez_id_str = row["EntrezGene ID"]
            if entrez_id_str == "" or entrez_id_str == "null":
                continue
            entrez_id = int(entrez_id_str)
            hgnc_id = row["HGNC ID"]
            rv[EntrezGene(entrez_id)].add(hgnc_id)
    return rv


def parse_mgi(
    mgi_fname: Path,
    hgnc_to_human_entrez: dict[str, EntrezGene],
    mgi_entrez_to_hgnc: dict[EntrezGene, set[str]],
) -> EntrezGeneMap:
    total = 0
    no_entrez_id = 0

    rows: list[dict[str, str]] = []
    withdrawn_map: dict[str, set[str]] = defaultdict(set)

    with open(mgi_fname, encoding="utf-8") as f:
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
                continue
            rows.append(row)
            total += 1

    def get_human_entrez_ids(row: dict[str, str]) -> set[EntrezGene]:
        mouse_entrez_id_str: str = str(row["Entrez Gene ID"])
        if mouse_entrez_id_str == "" or mouse_entrez_id_str == "null":
            get_sspsygene_logger().debug("MGI: No entrez id for %s", symbol)
            return set()
        mouse_entrez_id = int(mouse_entrez_id_str)
        hgnc_ids = mgi_entrez_to_hgnc.get(EntrezGene(mouse_entrez_id), None)
        if hgnc_ids is None:
            get_sspsygene_logger().debug("MGI: No hgnc id for %s", mouse_entrez_id)
            return set()
        rv: set[EntrezGene] = set()
        for hgnc_id in hgnc_ids:
            if hgnc_id not in hgnc_to_human_entrez:
                get_sspsygene_logger().debug("MGI: No human entrez id for %s", hgnc_id)
                continue
            rv.add(hgnc_to_human_entrez[hgnc_id])
        return rv

    symbols: set[str] = set()
    rv: list[EntrezGeneEntry] = []
    for row in rows:
        symbol = row["Marker Symbol"]
        assert symbol not in symbols, f"Symbol {symbol} is already known"
        symbols.add(symbol)
        human_entrez_ids = get_human_entrez_ids(row)
        if not human_entrez_ids:
            no_entrez_id += 1
            continue
        for human_entrez_id in human_entrez_ids:
            rv.append(EntrezGeneEntry(symbol, True, human_entrez_id))

    rv_synonyms: dict[str, set[EntrezGene]] = defaultdict(set)
    for row in rows:
        synonyms = [x for x in row["Synonyms"].split("|") if x != ""]
        human_entrez_ids = get_human_entrez_ids(row)
        if not human_entrez_ids:
            no_entrez_id += 1
            continue
        for synonym in synonyms:
            if synonym in symbols:
                get_sspsygene_logger().debug(
                    "Symbol %s is also a symbol",
                    synonym,
                )
                continue
            for human_entrez_id in human_entrez_ids:
                rv_synonyms[synonym].add(human_entrez_id)

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
