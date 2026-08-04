import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Iterable
from typing import Any, Literal, cast

import pandas as pd

from processing.types.data_load_result import DataLoadResult
from processing.types.gene_mapping import GeneMapping
from processing.types.entrez_gene import EntrezGene
from processing.types.link_table import LinkTable

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
        "condition",
        "organism",
        "organism_key",
        "fieldLabels",
        "columnLabels",
        "categories",
        "links",
        "in_path",
        "separator",
        "gene_mappings",
        "pvalue_column",
        "fdr_column",
        "effect_column",
        "meta_analysis",
        "why_excluded_from_meta_analysis",
        "overview_matrix",
        "overview_matrix_expand",
        "overview_matrix_phenotype_column",
        "overview_matrix_phenotype_columns",
        "overview_matrix_metric",
        "overview_matrix_metric_domain",
        "changelog",
        # Internal: dataset-level publication block, merged in by TablesConfig.
        "_publication",
        "publication",
        # Internal: dataset-level `deployTo` list and the dataset directory
        # name, stamped onto every table by TablesConfig.from_yaml_root (#225).
        # Note the *bare* `deployTo` is deliberately NOT recognized here — it is
        # a dataset-level key, so a wrangler who puts it under a table should
        # get the unknown-key warning below rather than a silently ignored flag.
        "_deploy_to",
        "_dataset",
    }
)

# Internal keys stamped in by the loader rather than written by a wrangler.
# Excluded from the "recognized keys" list in the unknown-key warning so we
# don't advertise them as things to type into a config.yaml.
_INTERNAL_TABLE_KEYS: frozenset[str] = frozenset(
    {"_publication", "_deploy_to", "_dataset"}
)


# Color-scale metric ids an expanded table may declare (`overview_matrix_metric`).
# The scale definitions (colors, kind, default domain) live in the web
# color-scale registry — this is only the id allowlist so config typos fail loud.
# `neglog_p` / `neglog_q` are inferred by default for p/fdr-based tables; the two
# effect-style metrics must be declared explicitly (their source columns aren't
# p-values).
_OVERVIEW_MATRIX_METRICS: frozenset[str] = frozenset(
    {"neglog_p", "neglog_q", "signed_neglog_p", "activity_ratio"}
)


def normalize_column_name(name: str) -> str:
    result = name.lower()
    result = re.sub(r"[^a-z0-9_]", "_", result)
    result = re.sub(r"_+", "_", result)
    return result


def get_sql_friendly_columns(df: pd.DataFrame) -> list[str]:
    return [normalize_column_name(col) for col in df.columns]


def normalize_field_labels(
    raw_labels: dict[str, str], context: str, label_kind: str = "fieldLabels"
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    seen_originals: dict[str, str] = {}  # normalized_key -> original_key
    for original_key, value in raw_labels.items():
        norm_key = normalize_column_name(original_key)
        if norm_key in seen_originals and seen_originals[norm_key] != original_key:
            raise ValueError(
                f'Conflicting {label_kind} in {context}: keys "{seen_originals[norm_key]}" and '
                f'"{original_key}" both normalize to "{norm_key}". '
                f"{label_kind} keys are case-insensitive — please remove the duplicate."
            )
        seen_originals[norm_key] = original_key
        normalized[norm_key] = value
    return normalized


def _title_case_token(token: str) -> str:
    """Uppercase the first character of a token, matching the frontend's
    naive `formatColumnHeader` title-casing (`\\b\\w` -> upper)."""
    return token[:1].upper() + token[1:] if token else token


def resolve_column_headers(
    display_columns: Iterable[str],
    column_labels: dict[str, str],
    token_map: dict[str, str],
) -> dict[str, str]:
    """Resolve display headers for column names (psypheno #210).

    For each column:
      - a per-table `column_labels` (whole-column) override wins outright;
      - otherwise the column is split on "_" and each token is replaced via
        `token_map` (the global `columnHeaderTokens` acronym map), with
        unmapped tokens title-cased.

    Only *non-trivial* entries are returned — i.e. columns with a per-table
    override or at least one token replaced by the map. Columns that would
    title-case identically to the frontend fallback are omitted, keeping the
    stored map compact and letting `formatColumnHeader()` handle the common
    case on the client.
    """
    resolved: dict[str, str] = {}
    for col in display_columns:
        override = column_labels.get(col)
        if override is not None:
            resolved[col] = override
            continue
        tokens = col.split("_")
        mapped_any = False
        parts: list[str] = []
        for token in tokens:
            replacement = token_map.get(token)
            if replacement is not None:
                parts.append(replacement)
                mapped_any = True
            else:
                parts.append(_title_case_token(token))
        if mapped_any:
            resolved[col] = " ".join(parts)
    return resolved


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
        # Constant (implicit) mappings have no source column and apply to every
        # row, so they never constrain the test-fixture filter.
        if gm.column_name is None:
            continue
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
    gene_mappings: list[GeneMapping]
    separator: str
    short_label: str | None = None
    medium_label: str | None = None
    long_label: str | None = None
    links: list[DatasetLink] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    source: str | None = None
    assay: list[str] = field(default_factory=list)
    condition: list[str] = field(default_factory=list)
    field_labels: dict[str, str] = field(default_factory=dict)
    # Per-table whole-column header overrides (#210): normalized column name ->
    # display header. Distinct from field_labels (the "?" tooltip). No global
    # base merge — the global acronym map is per-token, applied at load time.
    column_labels: dict[str, str] = field(default_factory=dict)
    organism: str | None = None
    organism_key: list[str] = field(default_factory=list)
    pvalue_column: str | None = None
    fdr_column: str | None = None
    effect_column: str | None = None
    # Whether this table's p-values feed the cross-study meta-analysis
    # (/most-significant). Default True. Set `meta_analysis: false` in the YAML
    # to keep the dataset fully browsable while excluding it from the combined
    # p-values — e.g. for tables whose p-values aren't comparable disease-DEG
    # evidence (Seurat cluster-marker tables, see #187). When excluded, record
    # the reason in `why_excluded_from_meta_analysis` so it's self-documenting.
    meta_analysis: bool = True
    why_excluded_from_meta_analysis: str | None = None
    # Whether this table is a source for the collated cross-modality overview
    # matrix (psypheno #212, "red table"). Opt-in: default False. Set
    # `overview_matrix: true` in the YAML on tables that are genuine consortium
    # perturbation experiments — a known gene was experimentally perturbed and a
    # modality readout exists (CRISPR(i) screens, Perturb-seq/-FISH, behavioral
    # assays, ASD-mutation organoid DE, …). Left False for curated/phenotype
    # annotation DBs (ClinVar/SFARI/MGI), GRN-inference networks (inferred, not
    # perturbed), and observational postmortem cohorts (no molecular diagnosis).
    # The /api/collated-matrix rows come only from labeled tables, so this is the
    # single, self-documenting allowlist — no name/category heuristics.
    overview_matrix: bool = False
    # Whether this table's modality column *expands* into one sub-column per
    # measured (target) gene in the overview matrix (psypheno #222). Opt-in on
    # top of `overview_matrix`. The sub-column axis is the table's target gene
    # column; a target qualifies when it is FDR-significant across at least N
    # distinct perturbed-side groups (for the ASD organoid table, N distinct CNV
    # regions), and each cell carries -log10 of the most significant raw p-value
    # for that (perturbed gene, target gene) pair. Requires both a perturbed and
    # a target gene mapping plus pvalue_column and fdr_column.
    overview_matrix_expand: bool = False
    # The expansion column axis for a non-gene modality (psypheno #213). Exactly
    # one axis must resolve: the table's `target` gene mapping (gene columns), OR
    # `overview_matrix_phenotype_column` (LONG: a text column whose distinct
    # values are the columns — e.g. Behavioral_Parameter, subcluster), OR
    # `overview_matrix_phenotype_columns` (WIDE: a fixed list of value columns,
    # each one column — e.g. brain regions, behavior parameters). Stored
    # normalized to match the loaded table's column names.
    overview_matrix_phenotype_column: str | None = None
    overview_matrix_phenotype_columns: list[str] = field(default_factory=list)
    # Color-scale metric id (see `_OVERVIEW_MATRIX_METRICS`). None → inferred at
    # materialization (`neglog_p`, or `neglog_q` when only an FDR/qval exists).
    # Required explicitly for WIDE effect tables whose values aren't p-values.
    overview_matrix_metric: str | None = None
    # Optional [lo, hi] override of the metric's default color-scale domain.
    overview_matrix_metric_domain: list[float] | None = None
    publication_title: str | None = None
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
    # The dataset directory name this table was defined in (data/datasets/<name>),
    # stamped in from the config.yaml's location (#225). Nothing else in a table
    # config carries it, which is why central_gene.dataset_names historically
    # holds *table* names.
    dataset: str = ""
    # Which site instances this table's dataset may be served on — the dataset's
    # `deployTo:` list, normalized to INSTANCE_ORDER (#225). Mandatory in the
    # YAML and validated there; the empty default exists only so the dataclass
    # field ordering works, and __post_init__ rejects it.
    deploy_to: frozenset[str] = frozenset()

    # short_label is a code/link identifier: lowercase letters, digits, underscores only
    _SHORT_LABEL_RE = re.compile(r"^[a-z0-9_]+$")

    def __post_init__(self):
        # Belt-and-braces (#225): config.py validates deployTo per config.yaml
        # with a message naming the file, but nothing may construct a table with
        # no declared destination — an undeclared table is one that could be
        # promoted anywhere.
        if not self.deploy_to:
            raise ValueError(
                f"table {self.table}: no deploy_to — the dataset's config.yaml "
                f"must declare a top-level `deployTo` list including `dev`."
            )
        if not self.dataset:
            raise ValueError(
                f"table {self.table}: no dataset name — tables must be loaded "
                f"from a data/datasets/<name>/config.yaml."
            )
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
        # A reason without an exclusion is almost certainly a mistake (the
        # author meant to also set meta_analysis: false). Flag it loudly.
        if self.why_excluded_from_meta_analysis and self.meta_analysis:
            raise ValueError(
                f"table {self.table}: why_excluded_from_meta_analysis is set but "
                f"meta_analysis is still true — set `meta_analysis: false` to "
                f"actually exclude it, or drop the reason."
            )
        # An expanded modality column is built from a column axis (the
        # sub-columns), the perturbed-gene axis (the matrix rows / significance
        # groups), and a metric/value. The column axis is exactly one of: a target
        # gene mapping (genes), a phenotype text column (LONG), or a list of
        # phenotype value columns (WIDE). Without a resolvable axis the
        # materializer would silently emit nothing, so fail loudly at config load.
        if self.overview_matrix_expand:
            missing: list[str] = []
            if not self.overview_matrix:
                missing.append("overview_matrix: true")
            if num_perturbed == 0:
                missing.append("a perturbed gene_mapping")

            axes = [
                ("a target gene_mapping", num_target > 0),
                ("overview_matrix_phenotype_column", bool(self.overview_matrix_phenotype_column)),
                ("overview_matrix_phenotype_columns", bool(self.overview_matrix_phenotype_columns)),
            ]
            n_axes = sum(1 for _, present in axes if present)
            wide = bool(self.overview_matrix_phenotype_columns)
            if n_axes == 0:
                missing.append(
                    "a column axis (a target gene_mapping, "
                    "overview_matrix_phenotype_column, or "
                    "overview_matrix_phenotype_columns)"
                )
            elif n_axes > 1:
                raise ValueError(
                    f"table {self.table}: overview_matrix_expand needs exactly one "
                    f"column axis, but "
                    f"{', '.join(name for name, present in axes if present)} are all set."
                )

            # Gene/LONG-phenotype tables color from a p/fdr column (default metric
            # neglog_p / neglog_q). WIDE tables carry the value in the columns
            # themselves and must name the metric explicitly (they aren't p-values).
            if wide:
                if not self.overview_matrix_metric:
                    missing.append(
                        "overview_matrix_metric (required for "
                        "overview_matrix_phenotype_columns)"
                    )
            elif not self.pvalue_column and not self.fdr_column:
                missing.append("a pvalue_column or fdr_column")

            if self.overview_matrix_metric and (
                self.overview_matrix_metric not in _OVERVIEW_MATRIX_METRICS
            ):
                raise ValueError(
                    f"table {self.table}: overview_matrix_metric "
                    f"{self.overview_matrix_metric!r} is not one of "
                    f"{sorted(_OVERVIEW_MATRIX_METRICS)}."
                )
            if self.overview_matrix_metric_domain is not None and (
                len(self.overview_matrix_metric_domain) != 2
            ):
                raise ValueError(
                    f"table {self.table}: overview_matrix_metric_domain must be "
                    f"[lo, hi]; got {self.overview_matrix_metric_domain!r}."
                )
            if missing:
                raise ValueError(
                    f"table {self.table}: overview_matrix_expand requires "
                    f"{', '.join(missing)}."
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
                sorted(_KNOWN_TABLE_KEYS - _INTERNAL_TABLE_KEYS),
            )
        publication: dict[str, Any] = (
            json_data.get("_publication") or json_data.get("publication") or {}
        )
        # Stamped in by TablesConfig.from_yaml_root; validated there against
        # INSTANCE_ORDER with the offending config.yaml path in the message.
        deploy_to = frozenset(json_data.get("_deploy_to") or ())
        dataset = str(json_data.get("_dataset") or "")
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

        # Condition: normalize string to list
        raw_disease = json_data.get("condition", [])
        if isinstance(raw_disease, str):
            condition = [raw_disease]
        else:
            condition = list(raw_disease)

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

        # Column labels: per-table whole-column header overrides (#210). Keys
        # are normalized to match SQL column names. Unlike field labels there is
        # no global base to merge — the global acronym handling is per-token
        # (columnHeaderTokens), applied later at load time.
        column_labels = normalize_field_labels(
            json_data.get("columnLabels", {}),
            context=f"table {table_name}",
            label_kind="columnLabels",
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

        # Meta-analysis inclusion flag (#187). Defaults to True; only an explicit
        # `meta_analysis: false` excludes the table from the combined p-values.
        meta_analysis = bool(json_data.get("meta_analysis", True))
        why_excluded = json_data.get("why_excluded_from_meta_analysis")
        if why_excluded is not None and not isinstance(why_excluded, str):
            raise ValueError(
                f"table {table_name}: why_excluded_from_meta_analysis must be a "
                f"string; got {type(why_excluded).__name__}"
            )

        # Overview-matrix inclusion flag (#212). Opt-in; defaults to False.
        overview_matrix = bool(json_data.get("overview_matrix", False))
        # Expanded-modality flag (#222). Opt-in on top of overview_matrix.
        overview_matrix_expand = bool(json_data.get("overview_matrix_expand", False))
        # Non-gene expansion axis (#213). Phenotype column names are stored
        # normalized so they match the loaded table's DB column names; their raw
        # form is recovered for display from fieldLabels / prettified at render.
        raw_phenotype_col = json_data.get("overview_matrix_phenotype_column")
        overview_matrix_phenotype_column = (
            normalize_column_name(raw_phenotype_col) if raw_phenotype_col else None
        )
        # Kept RAW (not normalized): the wide-axis materializer normalizes each
        # to read the loaded DB column but uses the raw name as the short column
        # header label (e.g. "Optic Tectum", "ActivityD").
        overview_matrix_phenotype_columns = [
            str(c) for c in (json_data.get("overview_matrix_phenotype_columns") or [])
        ]
        overview_matrix_metric = json_data.get("overview_matrix_metric")
        raw_metric_domain = json_data.get("overview_matrix_metric_domain")
        overview_matrix_metric_domain = (
            [float(v) for v in raw_metric_domain]
            if raw_metric_domain is not None
            else None
        )

        return cls(
            table=json_data["table"],
            description=json_data["description"],
            in_path=base_dir / json_data["in_path"],
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
            condition=condition,
            field_labels=merged_field_labels,
            column_labels=column_labels,
            organism=json_data.get("organism"),
            organism_key=organism_key,
            pvalue_column=pvalue_column,
            fdr_column=fdr_column,
            effect_column=effect_column,
            meta_analysis=meta_analysis,
            why_excluded_from_meta_analysis=why_excluded,
            overview_matrix=overview_matrix,
            overview_matrix_expand=overview_matrix_expand,
            overview_matrix_phenotype_column=overview_matrix_phenotype_column,
            overview_matrix_phenotype_columns=overview_matrix_phenotype_columns,
            overview_matrix_metric=overview_matrix_metric,
            overview_matrix_metric_domain=overview_matrix_metric_domain,
            publication_title=publication.get("title"),
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
            dataset=dataset,
            deploy_to=deploy_to,
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
            gene_mapping.column_name: "object"
            for gene_mapping in self.gene_mappings
            if gene_mapping.column_name is not None
        }
        data = pd.read_csv(
            self.in_path, sep=self.separator, dtype=gene_column_dtypes
        ).convert_dtypes(**conversion_dict)
        assert "id" not in data.columns, "id column already exists in data"
        # add id column:
        display_columns = get_sql_friendly_columns(data)
        data["id"] = list(range(len(data)))
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
            # Constant (implicit) mappings contribute no display gene column.
            if not conversion.multi_gene_separator and conversion.column_name is not None:
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
