from functools import lru_cache
import json
import logging
import os
from pathlib import Path
from typing import Any, TypedDict, List, TYPE_CHECKING

import yaml

from processing.instances import INSTANCE_ORDER, REQUIRED_DESTINATION

if TYPE_CHECKING:
    # Imported only for type checking to avoid circular import at runtime
    from processing.types.table_to_process_config import TableToProcessConfig

logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    """Read a required SSPSYGENE_* environment variable, raising a clear,
    user-facing error (not a raw KeyError) when it's unset. Callers in the
    Click layer catch ValueError and print it cleanly."""
    value = os.environ.get(name)
    if not value:
        raise ValueError(
            f"{name} is not set. Export it to the absolute path it names "
            f"(see the pre-meeting-setup tutorial). Every database read/write "
            f"resolves through SSPSYGENE_DATA_DB — there is no default."
        )
    return value


class GeneMapConfig:
    def __init__(self, super_base_dir: Path, gene_map_config: dict[str, str]):
        self.super_base_dir = super_base_dir
        self.hgnc_file = self.super_base_dir / gene_map_config["hgnc"]
        self.mgi_file = self.super_base_dir / gene_map_config["mgi"]
        self.zfin_file = self.super_base_dir / gene_map_config["zfin"]
        self.alliance_homology_file = (
            self.super_base_dir / gene_map_config["alliance_homology_file"]
        )
        nimh = gene_map_config.get("nimh_gene_list")
        self.nimh_gene_list_file: Path | None = (
            self.super_base_dir / nimh if nimh else None
        )
        tf = gene_map_config.get("tf_list")
        self.tf_list_file: Path | None = (
            self.super_base_dir / tf if tf else None
        )


class GlobalConfig(TypedDict, total=False):
    fieldLabels: dict[str, str]
    # Global per-token acronym map for column headers (#210): token -> display
    # text (e.g. asd -> ASD, logfc -> logFC). Applied token-by-token to every
    # column name at load time so a small map fixes acronym casing site-wide.
    columnHeaderTokens: dict[str, str]
    assayTypes: dict[str, str]
    conditionTypes: dict[str, str]
    organismTypes: dict[str, str]
    # Modality taxonomy for the overview matrix (#211): ordered list of
    # user-facing columns, each {key, label, assayTypes: [...], alwaysShow?}.
    # A superset of assayTypes — see data/datasets/globals.yaml.
    modalities: list[dict[str, Any]]


class YamlTablesFile(TypedDict, total=False):
    tables: List[dict[str, Any]]
    publication: dict[str, Any]
    maintainers: List[dict[str, Any]]
    deployTo: List[str]


# Recognized top-level keys in a per-dataset config.yaml. Mirrors
# _KNOWN_TABLE_KEYS in types/table_to_process_config.py: an unrecognized key is
# warned about rather than silently ignored, so `deployto:` / `deplyTo:` typos
# surface instead of silently disarming the deployTo safety flag (#225).
_KNOWN_DATASET_KEYS = frozenset(
    {
        "publication",
        "maintainers",
        "tables",
        "deployTo",
    }
)


def _parse_deploy_to(loaded: dict[str, Any], yaml_path: Path) -> list[str]:
    """Validate and normalize a dataset's `deployTo` list (#225).

    `deployTo` declares which site instances a dataset may appear on. It is
    mandatory and has no default: the failure mode of a silent default is
    publishing embargoed data, so every malformed form is a hard error naming
    the offending file. `dev` must always be listed explicitly even though it
    is present in every dataset — explicit beats implicit for a safety flag.
    """
    valid = ", ".join(INSTANCE_ORDER)
    hint = (
        f"Add a top-level `deployTo:` list naming the instances this dataset "
        f"may be served on (valid: {valid}); `dev` is required. Example:\n"
        f"    deployTo:\n      - dev\n      - int\n      - prod"
    )

    if "deployTo" not in loaded:
        raise ValueError(f"{yaml_path}: missing required top-level `deployTo`. {hint}")

    deploy_to = loaded["deployTo"]
    if not isinstance(deploy_to, list):
        raise ValueError(
            f"{yaml_path}: `deployTo` must be a list, got "
            f"{type(deploy_to).__name__}. {hint}"
        )
    if not deploy_to:
        raise ValueError(f"{yaml_path}: `deployTo` is empty. {hint}")

    unknown = [d for d in deploy_to if d not in INSTANCE_ORDER]
    if unknown:
        raise ValueError(
            f"{yaml_path}: `deployTo` contains unknown instance(s) "
            f"{sorted(unknown)}. Valid instances: {valid}."
        )
    if REQUIRED_DESTINATION not in deploy_to:
        raise ValueError(
            f"{yaml_path}: `deployTo` must include `{REQUIRED_DESTINATION}` — "
            f"dev is the build superset that int and prod are subsetted from. "
            f"Got {sorted(deploy_to)}."
        )

    # Normalize to INSTANCE_ORDER so downstream comparisons and the DB rows are
    # order-stable regardless of how the wrangler wrote the list.
    return [inst for inst in INSTANCE_ORDER if inst in deploy_to]


class TablesConfig:
    def __init__(self, tables: list["TableToProcessConfig"]):
        self.tables = tables

    @classmethod
    def from_yaml_root(
        cls,
        data_base_dir: Path,
        tables_root: Path,
        dataset: str | None = None,
        global_config: "GlobalConfig | None" = None,
    ) -> "TablesConfig":
        """
        Recursively discover per-dataset config.yaml files and load table configs.

        - `data_base_dir` is the value of SSPSYGENE_DATA_DIR.
        - `tables_root` is a path (relative to data_base_dir) that contains all
          dataset subdirectories. Each dataset directory may contain a config.yaml
          describing one or more tables.
        - `dataset` is an optional dataset directory name to load. If provided,
          only the config.yaml in that specific dataset directory is loaded.
        - `global_config` provides global field labels and assay type definitions.
        """
        root_dir = data_base_dir / tables_root
        if not root_dir.exists():
            raise FileNotFoundError(f"tables_root directory does not exist: {root_dir}")

        # Local import to avoid circular dependency with central_gene_table
        from processing.types.table_to_process_config import TableToProcessConfig

        global_field_labels: dict[str, str] = (global_config or {}).get("fieldLabels", {})

        if dataset is not None:
            dataset_yaml = root_dir / dataset / "config.yaml"
            if not dataset_yaml.exists():
                raise FileNotFoundError(
                    f"config.yaml not found for dataset '{dataset}': {dataset_yaml}"
                )
            yaml_paths = [dataset_yaml]
        else:
            yaml_paths = sorted(root_dir.rglob("config.yaml"))

        tables: list[TableToProcessConfig] = []
        for yaml_path in yaml_paths:
            try:
                with open(yaml_path, "r") as f:
                    loaded: YamlTablesFile | None = yaml.safe_load(f)  # type: ignore[assignment]
            except yaml.YAMLError as e:
                raise ValueError(
                    f"Error parsing YAML file {yaml_path}: {e}"
                ) from e

            if loaded is None:
                raise ValueError(
                    f"{yaml_path}: file is empty. Every dataset config.yaml must "
                    f"declare at least `deployTo` and `tables`."
                )

            unknown_keys = set(loaded) - _KNOWN_DATASET_KEYS
            if unknown_keys:
                logger.warning(
                    "%s: unknown top-level YAML key(s) %s — typo? Recognized "
                    "keys: %s",
                    yaml_path,
                    sorted(unknown_keys),
                    sorted(_KNOWN_DATASET_KEYS),
                )

            # Validated per file, BEFORE the table loop: a dataset with an empty
            # `tables:` list must still fail on a bad deployTo rather than pass
            # silently because the loop body never runs.
            deploy_to = _parse_deploy_to(loaded, yaml_path)

            table_entries = loaded.get("tables", [])
            publication = loaded.get("publication")
            # The dataset directory name. Stamped onto every table so the table
            # knows which dataset it came from — nothing else in the config
            # carries this today, which is why central_gene.dataset_names
            # actually holds *table* names (#225).
            dataset_name = yaml_path.parent.name

            # For each YAML file, in_path values are interpreted relative
            # to the directory containing that YAML file.
            base_dir_for_tables = yaml_path.parent
            for table_config in table_entries:
                # Merge dataset-level publication metadata into each table config
                merged_config: dict[str, Any] = dict(table_config)
                if publication:
                    merged_config["_publication"] = publication
                merged_config["_deploy_to"] = deploy_to
                merged_config["_dataset"] = dataset_name
                try:
                    tables.append(
                        TableToProcessConfig.from_json(
                            merged_config,
                            base_dir_for_tables,
                            global_field_labels=global_field_labels,
                        )
                    )
                except Exception as e:
                    table_name = table_config.get("table", "<unknown>")
                    raise ValueError(
                        f"Error loading table '{table_name}' from {yaml_path}: {e}"
                    ) from e

        return cls(tables)

    @classmethod
    def from_legacy_tables_list(
        cls, tables_config: list[dict[str, Any]], base_dir: Path
    ) -> "TablesConfig":
        """
        Backwards-compatible loader for the old JSON-based `tables` list.

        Unsupported since #225: a bare `tables` list has no per-dataset
        config.yaml, so it can carry neither a `deployTo` nor a dataset name,
        and a table with no declared destination must never reach the DB.
        """
        raise ValueError(
            "config.json uses the legacy `tables` list, which cannot declare "
            "the mandatory per-dataset `deployTo` (#225). Move the table "
            "definitions into data/datasets/<name>/config.yaml files and set "
            "`table_config_root` instead."
        )


class Config:
    def __init__(self, config_json_file: Path, dataset: str | None = None):
        with open(config_json_file, "r") as f:
            config = json.load(f)

        # Use environment variable for data directory to improve portability
        self.base_dir: Path = Path(
            _require_env("SSPSYGENE_DATA_DIR")
        )  # e.g., /absolute/path/to/data
        # SSPSYGENE_DATA_DB is the single source of truth for the dataset DB
        # path — the same variable the web app reads (web/lib/db.ts). load-db
        # writes it, the web app reads it; there is no config.json fallback and
        # no default, so the two sides can never diverge.
        self.out_db: Path = Path(_require_env("SSPSYGENE_DATA_DB"))
        # Combined-p-value meta-analysis lives in a separate SQLite file built
        # on its own cadence by `sspsygene meta-analysis` (issue #176). Honors
        # SSPSYGENE_META_DB (same override the web app uses); otherwise defaults
        # to a `-meta` sibling of out_db, so pointing SSPSYGENE_DATA_DB at a
        # scratch file (e.g. sspsygene-claude.db) yields a matching
        # sspsygene-claude-meta.db without extra plumbing.
        meta_override = os.environ.get("SSPSYGENE_META_DB")
        if meta_override:
            self.meta_db: Path = Path(meta_override)
        else:
            self.meta_db = self.out_db.with_name(
                f"{self.out_db.stem}-meta{self.out_db.suffix}"
            )
        # The collated overview matrix (#222) lives in its own SQLite file too,
        # built on its own cadence by `sspsygene overview-matrix` — the same
        # separate-file pattern as the meta-analysis, so the main dataset DB
        # stays lean and the matrix can be rebuilt/deployed independently.
        # Honors SSPSYGENE_OVERVIEW_DB (the same override the web app reads);
        # otherwise a `-overview` sibling of out_db.
        overview_override = os.environ.get("SSPSYGENE_OVERVIEW_DB")
        if overview_override:
            self.overview_db: Path = Path(overview_override)
        else:
            self.overview_db = self.out_db.with_name(
                f"{self.out_db.stem}-overview{self.out_db.suffix}"
            )
        # The canonical 259-gene SSPsyGene consortium panel. Never used to filter
        # *ingestion* (psypheno#23: "we always add all the genes") — it is a
        # display/filter concern. Today its one consumer is the overview matrix,
        # whose rows are restricted to consortium genes.
        self.sspsygene_gene_list: Path = self.base_dir / "sspsygene_genes.txt"
        self.gene_map_config = GeneMapConfig(self.base_dir, config["gene_map_files"])

        # Load global config (field labels, assay types) if specified
        self.global_config: GlobalConfig = {}
        if "global_config" in config:
            global_yaml_path = self.base_dir / config["global_config"]
            if global_yaml_path.exists():
                with open(global_yaml_path, "r") as f:
                    loaded_global = yaml.safe_load(f)
                if loaded_global:
                    self.global_config = loaded_global

        # New: load table configurations from per-dataset YAML files,
        # discovered recursively from the configured root directory.
        if "table_config_root" in config:
            tables_root = Path(config["table_config_root"])
            self.tables_config = TablesConfig.from_yaml_root(
                self.base_dir, tables_root, dataset=dataset,
                global_config=self.global_config,
            )
        elif "tables" in config:
            # Fallback for legacy configs that still embed the tables list.
            self.tables_config = TablesConfig.from_legacy_tables_list(
                config["tables"], self.base_dir
            )
        else:
            raise KeyError("Config must define either 'table_config_root' or 'tables'.")


@lru_cache(maxsize=None)
def get_sspsygene_config(dataset: str | None = None) -> "Config":
    return Config(Path(os.environ["SSPSYGENE_CONFIG_JSON"]), dataset=dataset)
