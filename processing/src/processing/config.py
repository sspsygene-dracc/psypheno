from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any


class GeneMapConfig:
    def __init__(self, super_base_dir: Path, gene_map_config: dict[str, str]):
        self.super_base_dir = super_base_dir
        self.hgnc_file = self.super_base_dir / gene_map_config["hgnc"]
        self.mgi_file = self.super_base_dir / gene_map_config["mgi"]
        self.zfin_file = self.super_base_dir / gene_map_config["zfin"]


class TablesConfig:
    def __init__(self, tables_config: list[dict[str, Any]]):
        # pylint: disable=import-outside-toplevel
        from processing.types.table_to_process_config import TableToProcessConfig

        self.tables = [
            TableToProcessConfig.from_json(table_config)
            for table_config in tables_config
        ]


class Config:
    def __init__(self, config_json_file: Path):
        with open(config_json_file, "r") as f:
            config = json.load(f)
        self.base_dir: Path = Path(config["basedir"])
        self.out_db: Path = self.base_dir / config["out_db"]
        self.gene_map_config = GeneMapConfig(self.base_dir, config["gene_map_files"])
        self.tables_config = TablesConfig(config["tables"])


@lru_cache(maxsize=1)
def get_sspsygene_config() -> Config:
    return Config(Path(os.environ["SSPSYGENE_CONFIG_JSON"]))
