from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from processing.types.data_load_result import DataLoadResult
from processing.types.gene_mapping import GeneMapping
from processing.types.entrez_gene import EntrezGene
from processing.types.link_table import LinkTable
from processing.types.split_column_entry import SplitColumnEntry


def get_sql_friendly_columns(df: pd.DataFrame) -> list[str]:
    return list(
        df.columns.str.lower()
        .str.replace(r"[^a-z0-9_]", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
    )


@dataclass
class TableToProcessConfig:
    table: str
    description: str
    in_path: Path
    split_column_map: list[SplitColumnEntry]
    gene_mappings: list[GeneMapping]
    separator: str
    short_label: str | None = None
    long_label: str | None = None
    links: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    organism: str | None = None
    publication_first_author: str | None = None
    publication_last_author: str | None = None
    publication_year: int | None = None
    publication_journal: str | None = None
    publication_doi: str | None = None
    publication_pmid: str | None = None

    def __post_init__(self):
        num_perturbed = 0
        num_target = 0
        for gene_mapping in self.gene_mappings:
            if gene_mapping.is_perturbed:
                num_perturbed += 1
            if gene_mapping.is_target:
                num_target += 1
        if num_perturbed > 1:
            raise ValueError(
                f"table {self.table}: A table cannot have more than one perturbed central gene conversion"
            )
        if num_target > 1:
            raise ValueError(
                f"table {self.table}: A table cannot have more than one target central gene conversion"
            )
        if num_perturbed != num_target:
            raise ValueError(
                f"table {self.table}: A table must have exactly one perturbed and one target central gene conversion, or none"
            )
        assert (num_perturbed == 0 and num_target == 0) or (
            num_perturbed == 1 and num_target == 1
        ), f"for table {self.table}: num_perturbed: {num_perturbed}, num_target: {num_target}"

    @classmethod
    def from_json(
        cls, json_data: dict[str, Any], base_dir: Path
    ) -> "TableToProcessConfig":
        publication: dict[str, Any] = json_data.get("_publication") or json_data.get("publication") or {}
        authors: list[str] = list(publication.get("authors", [])) if isinstance(
            publication.get("authors", []), list
        ) else []
        first_author = authors[0] if authors else None
        last_author = authors[-1] if authors else None
        year_val = publication.get("year")
        year_int: int | None
        try:
            year_int = int(year_val) if year_val is not None else None
        except (TypeError, ValueError):
            year_int = None

        return cls(
            table=json_data["table"],
            description=json_data["description"],
            in_path=base_dir / json_data["in_path"],
            split_column_map=[
                SplitColumnEntry.from_json(split_column_map)
                for split_column_map in json_data["split_column_map"]
            ],
            gene_mappings=[
                GeneMapping.from_json(gene_mapping)
                for gene_mapping in json_data["gene_mappings"]
            ],
            separator=json_data["separator"] if "separator" in json_data else "\t",
            short_label=json_data.get("shortLabel"),
            long_label=json_data.get("longLabel"),
            links=list(json_data.get("links", [])),
            categories=list(json_data.get("categories", [])),
            organism=json_data.get("organism"),
            publication_first_author=first_author,
            publication_last_author=last_author,
            publication_year=year_int,
            publication_journal=publication.get("journal"),
            publication_doi=publication.get("doi"),
            publication_pmid=publication.get("pmid"),
        )

    def load_data_table(self) -> DataLoadResult:
        conversion_dict: dict[str, Any] = {
            "convert_string": True,
            "convert_integer": False,
            "convert_boolean": False,
            "convert_floating": False,
        }
        gene_column_dtypes: Any = {
            gene_mapping.column_name: "object" for gene_mapping in self.gene_mappings
        }
        data = pd.read_csv(
            self.in_path, sep=self.separator, dtype=gene_column_dtypes
        ).convert_dtypes(**conversion_dict)
        assert "id" not in data.columns, "id column already exists in data"
        # add id column:
        display_columns = get_sql_friendly_columns(data)
        data["id"] = list(range(len(data)))
        for split_column in self.split_column_map:
            split_column.split_column(data)
        species_list: list[Literal["human", "mouse", "zebrafish"]] = []
        gene_columns: list[str] = []
        used_entrez_ids: set[EntrezGene] = set()
        link_tables: list[LinkTable] = []
        for conversion in self.gene_mappings:
            gene_columns.append(conversion.column_name.lower())
            species_list.append(conversion.species)
            link_table = conversion.resolve_to_central_gene_table(
                primary_table_name=self.table,
                data=data,
                in_path=self.in_path,
            )
            link_tables.append(link_table)
        species_set: set[Literal["human", "mouse", "zebrafish"]] = set(species_list)
        assert (
            len(species_set) == 1
        ), "No or multiple species in the same table: " + str(species_list)
        species = species_set.pop()
        data.columns = get_sql_friendly_columns(data)
        scalar_columns: list[str] = [
            x
            for x in display_columns
            if data[x].dtype == "float64" and x not in set(gene_columns) and x != "id"
        ]
        return DataLoadResult(
            data=data,
            gene_columns=gene_columns,
            gene_species=species,
            display_columns=display_columns,
            scalar_columns=scalar_columns,
            used_entrez_ids=used_entrez_ids,
            link_tables=link_tables,
        )
