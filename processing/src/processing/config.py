from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any, TypedDict, List, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    # Imported only for type checking to avoid circular import at runtime
    from processing.types.table_to_process_config import TableToProcessConfig


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
    assayTypes: dict[str, str]
    diseaseTypes: dict[str, str]
    organismTypes: dict[str, str]


class YamlTablesFile(TypedDict, total=False):
    tables: List[dict[str, Any]]
    publication: dict[str, Any]


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
                continue

            table_entries = loaded.get("tables", [])
            publication = loaded.get("publication")

            # For each YAML file, in_path values are interpreted relative
            # to the directory containing that YAML file.
            base_dir_for_tables = yaml_path.parent
            for table_config in table_entries:
                # Merge dataset-level publication metadata into each table config
                merged_config: dict[str, Any] = dict(table_config)
                if publication:
                    merged_config["_publication"] = publication
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
        """
        # Local import to avoid circular dependency with central_gene_table
        from processing.types.table_to_process_config import TableToProcessConfig

        tables = [
            TableToProcessConfig.from_json(table_config, base_dir)
            for table_config in tables_config
        ]
        return cls(tables)


class Config:
    def __init__(self, config_json_file: Path, dataset: str | None = None):
        with open(config_json_file, "r") as f:
            config = json.load(f)

        # Use environment variable for data directory to improve portability
        self.base_dir: Path = Path(
            os.environ["SSPSYGENE_DATA_DIR"]
        )  # e.g., /absolute/path/to/data
        self.out_db: Path = self.base_dir / config["out_db"]
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
