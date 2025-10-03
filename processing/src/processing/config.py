from functools import lru_cache
import json
import os
from pathlib import Path


class GeneMapConfig:
    def __init__(self, super_base_dir: Path, gene_map_config: dict[str, str]):
        self.super_base_dir = super_base_dir
        self.hgnc_file = self.super_base_dir / gene_map_config["hgnc"]
        self.mgi_file = self.super_base_dir / gene_map_config["mgi"]
        self.zfin_file = self.super_base_dir / gene_map_config["zfin"]


class Config:
    def __init__(self, config_json_file: Path):
        with open(config_json_file, "r") as f:
            config = json.load(f)
        self.base_dir = Path(config["basedir"])
        self.gene_map_config = GeneMapConfig(self.base_dir, config["gene_map_files"])


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config(Path(os.environ["SSPSYGENE_CONFIG_JSON"]))
