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
                entrez_id = -1
            else:
                entrez_id = int(entrez_id_str)
            assert symbol not in rv
            rv[symbol].add(EntrezGene(entrez_id))
    get_sspsygene_logger().info(
        "HGNC: Total: %d, No entrez id: %d (%.2f%%)",
        total,
        no_entrez_id,
        no_entrez_id / total * 100,
    )
    return dict(rv)


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


def parse_mgi(fname: Path) -> dict[str, set[EntrezGene]]:
    rv: dict[str, set[EntrezGene]] = defaultdict(set)
    total = 0
    no_entrez_id = 0

    rows: list[dict[str, str]] = []

    with open(fname, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t", fieldnames=mgi_entrez_header)
        for row in reader:
            status = row["Status"]
            assert status in {"O", "W"}
            if status == "W":
                # these are not listed with entrez ids
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
            if elem_type != "Gene":
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
    for row in rows:
        symbol = row["Marker Symbol"]
        assert symbol not in rv, f"Symbol {symbol} already in rv"
        symbols.add(symbol)
        entrez_id = get_entrez_id(row)
        if entrez_id == -1:
            no_entrez_id += 1
        rv[symbol].add(EntrezGene(entrez_id))

    rv_synonyms: dict[str, set[EntrezGene]] = defaultdict(set)
    for row in rows:
        synonyms = [x for x in row["Synonyms"].split("|") if x != ""]
        entrez_id = get_entrez_id(row)
        for synonym in synonyms:
            if synonym in symbols:
                get_sspsygene_logger().debug(
                    "Symbol %s is also a symbol with entrez id %s",
                    synonym,
                    rv[synonym],
                )
                continue
            rv_synonyms[synonym].add(EntrezGene(entrez_id))

    rv_synonyms = {x: y for x, y in rv_synonyms.items() if len(y) == 1}
    rv.update(rv_synonyms)

    get_sspsygene_logger().info(
        "MGI: Total: %d, No entrez id: %d (%.2f%%)",
        total,
        no_entrez_id,
        no_entrez_id / total * 100,
    )
    return dict(rv)


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
                entrez_id = -1
            rv[symbol].add(EntrezGene(entrez_id))
    get_sspsygene_logger().info(
        "ZFIN: Total: %d, No entrez id: %d (%.2f%%)",
        total,
        no_entrez_id,
        no_entrez_id / total * 100,
    )
    return dict(rv)
