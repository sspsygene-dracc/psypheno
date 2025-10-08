from functools import lru_cache

from processing.config import get_sspsygene_config
from processing.sym_resolve import parse_hgnc, parse_mgi, parse_zfin
from processing.types.entrez_gene_map import EntrezGeneMap


@lru_cache(maxsize=1)
def get_entrez_gene_maps() -> dict[str, EntrezGeneMap]:
    return {
        "human": parse_hgnc(get_sspsygene_config().gene_map_config.hgnc_file),
        "mouse": parse_mgi(get_sspsygene_config().gene_map_config.mgi_file),
        "zebrafish": parse_zfin(get_sspsygene_config().gene_map_config.zfin_file),
    }
