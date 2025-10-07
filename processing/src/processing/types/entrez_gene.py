from dataclasses import dataclass


@dataclass(frozen=True)
class EntrezGene:
    entrez_id: int

    def __repr__(self) -> str:
        return str(self.entrez_id)
