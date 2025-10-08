from collections import defaultdict
from dataclasses import dataclass

from processing.types.entrez_gene import EntrezGene
from processing.types.entrez_gene_entry import EntrezGeneEntry


@dataclass(frozen=True)
class EntrezGeneMap:
    entrez_gene_entries: list[EntrezGeneEntry]

    def get_map(self) -> dict[str, set[EntrezGene]]:
        rv: dict[str, set[EntrezGene]] = defaultdict(set)
        for entry in self.entrez_gene_entries:
            rv[entry.name].add(entry.entrez_id)
        return dict(rv)
