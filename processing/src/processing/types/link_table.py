from dataclasses import dataclass

import pandas as pd
from processing.types.entrez_gene import EntrezGene


@dataclass
class LinkTable:
    links: list[tuple[int, EntrezGene]]
    gene_column_name: str
    link_table_name: str
    is_perturbed: bool
    is_target: bool

    def get_df(self) -> pd.DataFrame:
        links_int: list[tuple[int, int]] = [(x[0], x[1].entrez_id) for x in self.links]
        return pd.DataFrame(links_int, columns=["id", "entrez_gene"])

    def get_meta_entry(self) -> str:
        int_is_perturbed = "1" if self.is_perturbed else "0"
        int_is_target = "1" if self.is_target else "0"
        return f"{self.gene_column_name}:{self.link_table_name}:{int_is_perturbed}:{int_is_target}"
