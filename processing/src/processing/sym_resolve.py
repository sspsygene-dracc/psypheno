from collections import defaultdict
import csv
from pathlib import Path

from processing.my_logger import get_sspsygene_logger
from processing.types.entrez_gene import EntrezGene


def parse_hgnc(fname: Path) -> dict[str, set[EntrezGene]]:
    rv: dict[str, set[EntrezGene]] = defaultdict(set)
    total = 0
    no_entrez_id = 0
    with open(fname, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            total += 1
            symbol = row["symbol"]
            entrez_id_str = row["entrez_id"]
            if entrez_id_str == "":
                get_sspsygene_logger().debug("HGNC: No entrez id for %s", symbol)
                no_entrez_id += 1
                continue
            entrez_id = int(entrez_id_str)
            assert symbol not in rv
            rv[symbol].add(EntrezGene(entrez_id))
    get_sspsygene_logger().info(
        "HGNC: Total: %d, No entrez id: %d (%.2f%%)",
        total,
        no_entrez_id,
        no_entrez_id / total * 100,
    )
    return rv


def parse_mgi(fname: Path) -> dict[str, set[EntrezGene]]:
    rv: dict[str, set[EntrezGene]] = defaultdict(set)
    total = 0
    no_entrez_id = 0
    with open(fname, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            total += 1
            symbol = row["Marker Symbol"]
            entrez_id_str = row["EntrezGene ID"]
            if entrez_id_str == "" or entrez_id_str == "null":
                get_sspsygene_logger().debug("MGI: No entrez id for %s", symbol)
                no_entrez_id += 1
                continue
            entrez_id = int(entrez_id_str)
            assert symbol not in rv
            rv[symbol].add(EntrezGene(entrez_id))
    get_sspsygene_logger().info(
        "MGI: Total: %d, No entrez id: %d (%.2f%%)",
        total,
        no_entrez_id,
        no_entrez_id / total * 100,
    )
    return rv


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


def parse_zfin(fname: Path) -> dict[str, set[EntrezGene]]:
    rv: dict[str, set[EntrezGene]] = defaultdict(set)
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
                continue
            rv[symbol].add(EntrezGene(entrez_id))
    get_sspsygene_logger().info(
        "ZFIN: Total: %d, No entrez id: %d (%.2f%%)",
        total,
        no_entrez_id,
        no_entrez_id / total * 100,
    )
    return rv
