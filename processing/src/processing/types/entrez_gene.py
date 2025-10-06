from dataclasses import dataclass


@dataclass(frozen=True)
class EntrezGene:
    entrez_id: int
