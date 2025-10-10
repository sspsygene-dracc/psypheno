from dataclasses import dataclass

import pandas as pd
from processing.types.entrez_gene import EntrezGene


@dataclass
class LinkTable:
    links: list[tuple[int, EntrezGene]]
    gene_column_name: str
    link_table_name: str

    def get_df(self) -> pd.DataFrame:
        links_int: list[tuple[int, int]] = [(x[0], x[1].entrez_id) for x in self.links]
        return pd.DataFrame(links_int, columns=["id", "entrez_gene"])

    def get_meta_entry(self) -> str:
        return f"{self.gene_column_name}:{self.link_table_name}"
