from functools import lru_cache

from processing.config import get_sspsygene_config
from processing.sym_resolve import (
    parse_hgnc,
    parse_mgi,
    parse_mgi_entrez_to_hgnc,
    parse_zfin,
)
from processing.types.entrez_gene_map import EntrezGeneMap


@lru_cache(maxsize=1)
def get_entrez_gene_maps() -> dict[str, EntrezGeneMap]:
    hgnc_result = parse_hgnc(get_sspsygene_config().gene_map_config.hgnc_file)
    mgi_entrez_to_hgnc = parse_mgi_entrez_to_hgnc(
        get_sspsygene_config().gene_map_config.alliance_homology_file
    )
    mgi_result = parse_mgi(
        get_sspsygene_config().gene_map_config.mgi_file,
        hgnc_result.hgnc_id_to_human_entrez_id,
        mgi_entrez_to_hgnc,
    )
    zfin_result = parse_zfin(get_sspsygene_config().gene_map_config.zfin_file)
    return {
        "human": hgnc_result.entrez_gene_map,
        "mouse": mgi_result,
        "zebrafish": zfin_result,
    }
