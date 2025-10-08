from dataclasses import dataclass

from processing.types.entrez_gene import EntrezGene


@dataclass(frozen=True)
class EntrezGeneEntry:
    name: str
    is_symbol: bool
    entrez_id: EntrezGene
