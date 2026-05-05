from pathlib import Path

import pytest

from processing.preprocessing import GeneSymbolNormalizer
from processing.preprocessing.ensembl_index import EnsemblToSymbolMapper
from processing.preprocessing.gencode_clone_index import GencodeCloneIndex


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def normalizer() -> GeneSymbolNormalizer:
    return GeneSymbolNormalizer.from_paths(
        hgnc_file=FIXTURES / "hgnc_stub.txt",
        mgi_file=FIXTURES / "mgi_stub.rpt",
    )


@pytest.fixture(scope="session")
def ensembl_mapper() -> EnsemblToSymbolMapper:
    return EnsemblToSymbolMapper.from_paths(
        hgnc_file=FIXTURES / "hgnc_stub.txt",
        alliance_homology_file=FIXTURES / "alliance_homology_stub.rpt",
    )


@pytest.fixture(scope="session")
def gencode_clone_index() -> GencodeCloneIndex:
    return GencodeCloneIndex.from_paths(
        tsv_path=FIXTURES / "gencode_clone_map_stub.tsv",
    )
