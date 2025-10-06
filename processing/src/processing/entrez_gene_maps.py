from functools import lru_cache

from processing.config import get_config
from processing.sym_resolve import parse_hgnc, parse_mgi, parse_zfin
from processing.types.entrez_gene import EntrezGene


@lru_cache(maxsize=1)
def get_entrez_gene_maps() -> dict[str, dict[str, EntrezGene]]:
    return {
        "human": parse_hgnc(
            get_config().base_dir / "data" / "homology" / "hgnc_complete_set.txt"
        ),
        "mouse": parse_mgi(
            get_config().base_dir
            / "data"
            / "homology"
            / "MGI_HGNC_AllianceHomology.rpt"
        ),
        "zebrafish": parse_zfin(
            get_config().base_dir / "data" / "homology" / "zfin_human_orthos.txt"
        ),
    }
