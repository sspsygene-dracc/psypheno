from functools import lru_cache

from processing.config import get_sspsygene_config
from processing.sym_resolve import parse_hgnc, parse_mgi, parse_zfin
from processing.types.entrez_gene import EntrezGene


@lru_cache(maxsize=1)
def get_entrez_gene_maps() -> dict[str, dict[str, set[EntrezGene]]]:
    return {
        "human": dict(parse_hgnc(get_sspsygene_config().gene_map_config.hgnc_file)),
        "mouse": dict(parse_mgi(get_sspsygene_config().gene_map_config.mgi_file)),
        "zebrafish": dict(parse_zfin(get_sspsygene_config().gene_map_config.zfin_file)),
    }
