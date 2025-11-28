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


class YamlTablesFile(TypedDict):
    tables: List[dict[str, Any]]


class TablesConfig:
    def __init__(self, tables: list["TableToProcessConfig"]):
        self.tables = tables

    @classmethod
    def from_yaml_root(cls, data_base_dir: Path, tables_root: Path) -> "TablesConfig":
        """
        Recursively discover per-dataset config.yaml files and load table configs.

        - `data_base_dir` is the value of SSPSYGENE_DATA_DIR.
        - `tables_root` is a path (relative to data_base_dir) that contains all
          dataset subdirectories. Each dataset directory may contain a config.yaml
          describing one or more tables.
        """
        root_dir = data_base_dir / tables_root
        if not root_dir.exists():
            raise FileNotFoundError(f"tables_root directory does not exist: {root_dir}")

        # Local import to avoid circular dependency with central_gene_table
        from processing.types.table_to_process_config import TableToProcessConfig

        tables: list[TableToProcessConfig] = []
        for yaml_path in root_dir.rglob("config.yaml"):
            with open(yaml_path, "r") as f:
                loaded: YamlTablesFile | None = yaml.safe_load(f)  # type: ignore[assignment]

            if loaded is None:
                continue

            table_entries = loaded.get("tables", [])

            # For each YAML file, in_path values are interpreted relative
            # to the directory containing that YAML file.
            base_dir_for_tables = yaml_path.parent
            for table_config in table_entries:
                tables.append(
                    TableToProcessConfig.from_json(table_config, base_dir_for_tables)
                )

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
    def __init__(self, config_json_file: Path):
        with open(config_json_file, "r") as f:
            config = json.load(f)

        # Use environment variable for data directory to improve portability
        self.base_dir: Path = Path(
            os.environ["SSPSYGENE_DATA_DIR"]
        )  # e.g., /absolute/path/to/data
        self.out_db: Path = self.base_dir / config["out_db"]
        self.gene_map_config = GeneMapConfig(self.base_dir, config["gene_map_files"])

        # New: load table configurations from per-dataset YAML files,
        # discovered recursively from the configured root directory.
        if "table_config_root" in config:
            tables_root = Path(config["table_config_root"])
            self.tables_config = TablesConfig.from_yaml_root(self.base_dir, tables_root)
        elif "tables" in config:
            # Fallback for legacy configs that still embed the tables list.
            self.tables_config = TablesConfig.from_legacy_tables_list(
                config["tables"], self.base_dir
            )
        else:
            raise KeyError("Config must define either 'table_config_root' or 'tables'.")


@lru_cache(maxsize=1)
def get_sspsygene_config() -> "Config":
    return Config(Path(os.environ["SSPSYGENE_CONFIG_JSON"]))
