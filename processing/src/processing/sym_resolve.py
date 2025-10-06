import csv
from pathlib import Path
from processing.entrez_gene import EntrezGene


def parse_hgnc(fname: Path) -> dict[str, EntrezGene]:
    rv: dict[str, EntrezGene] = {}
    with open(fname, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            symbol = row["symbol"]
            entrez_id = int(row["entrez_id"])
            assert symbol not in rv
            rv[symbol] = EntrezGene(entrez_id)
    return rv


def parse_mgi(fname: Path) -> dict[str, EntrezGene]:
    rv: dict[str, EntrezGene] = {}
    with open(fname, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            symbol = row["Marker Symbol"]
            entrez_id = int(row["EntrezGene ID"])
            assert symbol not in rv
            rv[symbol] = EntrezGene(entrez_id)
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
    "ECO Term Name"
]

def parse_zfin(fname: Path) -> dict[str, EntrezGene]:
    rv: dict[str, EntrezGene] = {}
    with open(fname, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t", fieldnames=zfin_header)
        for row in reader:
            symbol = row["ZFIN Symbol"]
            entrez_id = int(row["Gene ID"])
            assert symbol not in rv
            rv[symbol] = EntrezGene(entrez_id)
    return rv
