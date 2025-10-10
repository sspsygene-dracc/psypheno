from dataclasses import dataclass
from typing import Literal

import pandas as pd
from processing.types.entrez_gene import EntrezGene
from processing.types.link_table import LinkTable


@dataclass
class DataLoadResult:
    data: pd.DataFrame
    link_tables: list[LinkTable]
    gene_columns: list[str]
    gene_species: Literal["human", "mouse", "zebrafish"]
    display_columns: list[str]
    scalar_columns: list[str]
    used_entrez_ids: set[EntrezGene]
