import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import pandas as pd

from processing.types.data_load_result import DataLoadResult
from processing.types.gene_mapping import GeneMapping
from processing.types.entrez_gene import EntrezGene
from processing.types.link_table import LinkTable
from processing.types.split_column_entry import SplitColumnEntry

logger = logging.getLogger(__name__)


@dataclass
class DatasetLink:
    url: str
    label: str | None = None
    description: str | None = None

    @classmethod
    def from_yaml(cls, raw: Any, table_name: str) -> "DatasetLink":
        if isinstance(raw, str):
            return cls(url=raw)
        if isinstance(raw, dict):
            url = raw.get("url")
            if not isinstance(url, str) or not url:
                raise ValueError(
                    f"table {table_name}: links entry must have a non-empty 'url' "
                    f"field; got {raw!r}"
                )
            label = raw.get("label")
            description = raw.get("description")
            if label is not None and not isinstance(label, str):
                raise ValueError(
                    f"table {table_name}: links[{url}].label must be a string; "
                    f"got {label!r}"
                )
            if description is not None and not isinstance(description, str):
                raise ValueError(
                    f"table {table_name}: links[{url}].description must be a "
                    f"string; got {description!r}"
                )
            return cls(url=url, label=label, description=description)
        raise ValueError(
            f"table {table_name}: links entry must be a URL string or a dict "
            f"with 'url'/'label'/'description'; got {type(raw).__name__}: {raw!r}"
        )

    def to_json_dict(self) -> dict[str, str]:
        out: dict[str, str] = {"url": self.url}
        if self.label is not None:
            out["label"] = self.label
        if self.description is not None:
            out["description"] = self.description
        return out


# Per-table YAML keys that the loader recognizes. Anything else is ignored
# silently today, which makes typos invisible — log a warning so wranglers
# notice (e.g. `data_downloads:` from old #80 context, `field_label:` typo).
_KNOWN_TABLE_KEYS: frozenset[str] = frozenset(
    {
        "table",
        "shortLabel",
        "mediumLabel",
        "longLabel",
        "description",
        "source",
        "assay",
        "disease",
        "organism",
        "organism_key",
        "fieldLabels",
        "categories",
        "links",
        "in_path",
        "separator",
        "split_column_map",
        "gene_mappings",
        "pvalue_column",
        "fdr_column",
        "effect_column",
        "changelog",
        # Internal: dataset-level publication block, merged in by TablesConfig.
        "_publication",
        "publication",
    }
)


def normalize_column_name(name: str) -> str:
    result = name.lower()
    result = re.sub(r"[^a-z0-9_]", "_", result)
    result = re.sub(r"_+", "_", result)
    return result


def get_sql_friendly_columns(df: pd.DataFrame) -> list[str]:
    return [normalize_column_name(col) for col in df.columns]


def normalize_field_labels(raw_labels: dict[str, str], context: str) -> dict[str, str]:
    normalized: dict[str, str] = {}
    seen_originals: dict[str, str] = {}  # normalized_key -> original_key
    for original_key, value in raw_labels.items():
        norm_key = normalize_column_name(original_key)
        if norm_key in seen_originals and seen_originals[norm_key] != original_key:
            raise ValueError(
                f'Conflicting fieldLabels in {context}: keys "{seen_originals[norm_key]}" and '
                f'"{original_key}" both normalize to "{norm_key}". '
                f"fieldLabels keys are case-insensitive — please remove the duplicate."
            )
        seen_originals[norm_key] = original_key
        normalized[norm_key] = value
    return normalized


_PER_GROUP_ROW_CAP = 200


def _filter_to_test_genes(
    *,
    data: pd.DataFrame,
    gene_mappings: list[GeneMapping],
    allowed_central_gene_ids: set[int],
) -> pd.DataFrame:
    """Restrict a dataset to rows whose gene-keyed columns hit the fixture.

    Two stages:
      1. Filter rows where EVERY column in `gene_mappings` carries a value
         resolving to a central_gene in `allowed_central_gene_ids` (AND
         semantics — for pair tables this means both ends are interesting;
         for single-direction tables it reduces to the one column).
      2. Cap each unique gene-key combination to `_PER_GROUP_ROW_CAP` rows,
         so a single perturbation × target pair (or a single gene's
         per-cell-type repeats) can't bloat the test build.

    Filtering runs before `resolve_to_central_gene_table` so we never
    create `manually_added=1` central_gene stubs from rows that get thrown
    away.
    """
    # Local import: central_gene_table imports config, which imports this
    # module — top-level import would cycle.
    from processing.central_gene_table import get_central_gene_table

    central_table = get_central_gene_table()
    keep_mask = pd.Series(True, index=data.index)
    group_cols: list[str] = []
    for gm in gene_mappings:
        species_map = central_table.get_species_map(species=gm.species)
        allowed_strs = {
            key
            for key, entries in species_map.items()
            if any(entry.row_id in allowed_central_gene_ids for entry in entries)
        }
        col = data[gm.column_name]
        if gm.multi_gene_separator:
            sep = gm.multi_gene_separator
            col_match = col.astype("string").apply(
                lambda s, _sep=sep, _allowed=allowed_strs: pd.notna(s)  # type: ignore
                and any(g.strip() in _allowed for g in str(s).split(_sep))  # type: ignore
            )
        else:
            col_match = col.isin(allowed_strs)  # type: ignore
        keep_mask &= col_match.fillna(False)
        group_cols.append(gm.column_name)
    filtered = data[keep_mask]
    if group_cols:
        filtered = filtered.groupby(
            group_cols,
            dropna=False,
            as_index=False,
            group_keys=False,
            sort=False,
        ).head(_PER_GROUP_ROW_CAP)
    return cast(pd.DataFrame, filtered.reset_index(drop=True))


@dataclass
class TableToProcessConfig:
    table: str
    description: str
    in_path: Path
    split_column_map: list[SplitColumnEntry]
    gene_mappings: list[GeneMapping]
    separator: str
    short_label: str | None = None
    medium_label: str | None = None
    long_label: str | None = None
    links: list[DatasetLink] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    source: str | None = None
    assay: list[str] = field(default_factory=list)
    disease: list[str] = field(default_factory=list)
    field_labels: dict[str, str] = field(default_factory=dict)
    organism: str | None = None
    organism_key: list[str] = field(default_factory=list)
    pvalue_column: str | None = None
    fdr_column: str | None = None
    effect_column: str | None = None
    publication_first_author: str | None = None
    publication_last_author: str | None = None
    publication_author_count: int | None = None
    publication_authors: list[str] = field(default_factory=list)
    publication_year: int | None = None
    publication_journal: str | None = None
    publication_doi: str | None = None
    publication_pmid: str | None = None
    publication_sspsygene_grants: list[str] = field(default_factory=list)
    changelog: list[dict[str, str]] = field(default_factory=list)

    # short_label is a code/link identifier: lowercase letters, digits, underscores only
    _SHORT_LABEL_RE = re.compile(r"^[a-z0-9_]+$")

    def __post_init__(self):
        if self.short_label is not None:
            if not self._SHORT_LABEL_RE.match(self.short_label):
                raise ValueError(
                    f"table {self.table}: short_label {self.short_label!r} contains "
                    f"disallowed characters. Only lowercase letters, digits, "
                    f"and underscores are allowed."
                )
        num_perturbed = sum(
            1 for gm in self.gene_mappings if gm.perturbed_or_target == "perturbed"
        )
        num_target = sum(
            1 for gm in self.gene_mappings if gm.perturbed_or_target == "target"
        )
        if num_perturbed > 1:
            raise ValueError(
                f"table {self.table}: A table cannot have more than one perturbed central gene conversion"
            )
        if num_target > 1:
            raise ValueError(
                f"table {self.table}: A table cannot have more than one target central gene conversion"
            )
        if num_perturbed + num_target == 0 and self.gene_mappings:
            raise ValueError(
                f"table {self.table}: At least one gene_mapping must be present"
            )

    @classmethod
    def from_json(
        cls,
        json_data: dict[str, Any],
        base_dir: Path,
        global_field_labels: dict[str, str] | None = None,
    ) -> "TableToProcessConfig":
        unknown = set(json_data.keys()) - _KNOWN_TABLE_KEYS
        if unknown:
            table_name = json_data.get("table", "<unknown>")
            logger.warning(
                "table %s: unknown YAML key(s) %s — typo? Recognized keys: %s",
                table_name,
                sorted(unknown),
                sorted(_KNOWN_TABLE_KEYS - {"_publication"}),
            )
        publication: dict[str, Any] = (
            json_data.get("_publication") or json_data.get("publication") or {}
        )
        authors: list[str] = (
            list(publication.get("authors", []))
            if isinstance(publication.get("authors", []), list)
            else []
        )
        first_author = authors[0] if authors else None
        last_author = authors[-1] if authors else None
        author_count = len(authors) if authors else None
        year_val = publication.get("year")
        year_int: int | None
        try:
            year_int = int(year_val) if year_val is not None else None
        except (TypeError, ValueError):
            year_int = None

        raw_grants = publication.get("sspsygene_grants", [])
        sspsygene_grants: list[str] = (
            [str(g) for g in raw_grants] if isinstance(raw_grants, list) else []
        )

        # Assay: normalize string to list
        raw_assay = json_data.get("assay", [])
        if isinstance(raw_assay, str):
            assay = [raw_assay]
        else:
            assay = list(raw_assay)

        # Disease: normalize string to list
        raw_disease = json_data.get("disease", [])
        if isinstance(raw_disease, str):
            disease = [raw_disease]
        else:
            disease = list(raw_disease)

        # Organism key: controlled vocabulary (e.g. "human", "mouse"); separate
        # from the free-form `organism` description. Normalize string to list.
        raw_organism_key = json_data.get("organism_key", [])
        if isinstance(raw_organism_key, str):
            organism_key = [raw_organism_key]
        else:
            organism_key = list(raw_organism_key)

        # Field labels: merge global defaults with per-table overrides
        # Keys are normalized (lowercased, sanitized) to match column names
        table_name = json_data["table"]
        merged_field_labels = normalize_field_labels(
            global_field_labels or {},
            context=f"global config for table {table_name}",
        )
        merged_field_labels.update(
            normalize_field_labels(
                json_data.get("fieldLabels", {}),
                context=f"table {table_name}",
            )
        )

        # P-value and FDR column names: normalize to match SQL column names.
        # Accepts a single string or a list of strings in config YAML.
        # Stored as comma-separated string internally.
        raw_pvalue_col = json_data.get("pvalue_column")
        if isinstance(raw_pvalue_col, list):
            pvalue_column = (
                ",".join(normalize_column_name(c) for c in raw_pvalue_col) or None
            )
        elif raw_pvalue_col:
            pvalue_column = normalize_column_name(raw_pvalue_col)
        else:
            pvalue_column = None

        raw_fdr_col = json_data.get("fdr_column")
        if isinstance(raw_fdr_col, list):
            fdr_column = ",".join(normalize_column_name(c) for c in raw_fdr_col) or None
        elif raw_fdr_col:
            fdr_column = normalize_column_name(raw_fdr_col)
        else:
            fdr_column = None

        raw_effect_col = json_data.get("effect_column")
        effect_column = (
            normalize_column_name(raw_effect_col) if raw_effect_col else None
        )

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
            medium_label=json_data.get("mediumLabel"),
            long_label=json_data.get("longLabel"),
            links=[
                DatasetLink.from_yaml(entry, table_name=json_data["table"])
                for entry in json_data.get("links", []) or []
            ],
            categories=list(json_data.get("categories", [])),
            source=json_data.get("source"),
            assay=assay,
            disease=disease,
            field_labels=merged_field_labels,
            organism=json_data.get("organism"),
            organism_key=organism_key,
            pvalue_column=pvalue_column,
            fdr_column=fdr_column,
            effect_column=effect_column,
            publication_first_author=first_author,
            publication_last_author=last_author,
            publication_author_count=author_count,
            publication_authors=authors,
            publication_year=year_int,
            publication_journal=publication.get("journal"),
            publication_doi=publication.get("doi"),
            publication_pmid=publication.get("pmid"),
            publication_sspsygene_grants=sspsygene_grants,
            changelog=list(json_data.get("changelog", [])),
        )

    def load_data_table(
        self,
        *,
        test_central_gene_ids: set[int] | None = None,
    ) -> DataLoadResult:
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
        if test_central_gene_ids is not None and self.gene_mappings:
            data = _filter_to_test_genes(
                data=data,
                gene_mappings=self.gene_mappings,
                allowed_central_gene_ids=test_central_gene_ids,
            )
        species_list: list[Literal["human", "mouse", "zebrafish"]] = []
        gene_columns: list[str] = []
        used_entrez_ids: set[EntrezGene] = set()
        link_tables: list[LinkTable] = []
        for conversion in self.gene_mappings:
            if not conversion.multi_gene_separator:
                gene_columns.append(normalize_column_name(conversion.column_name))
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
        # Validate pvalue/fdr columns exist (may be comma-separated list)
        col_set = set(data.columns)
        if self.pvalue_column:
            for pc in self.pvalue_column.split(","):
                if pc not in col_set:
                    raise ValueError(
                        f"table {self.table}: pvalue_column '{pc}' "
                        f"not found in data columns: {sorted(col_set)}"
                    )
        if self.fdr_column:
            for fc in self.fdr_column.split(","):
                if fc not in col_set:
                    raise ValueError(
                        f"table {self.table}: fdr_column '{fc}' "
                        f"not found in data columns: {sorted(col_set)}"
                    )
        if self.effect_column and self.effect_column not in col_set:
            raise ValueError(
                f"table {self.table}: effect_column '{self.effect_column}' "
                f"not found in data columns: {sorted(col_set)}"
            )
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
