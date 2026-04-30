from pathlib import Path

import pytest

from processing.preprocessing import GeneSymbolNormalizer
from processing.preprocessing.ensembl_index import EnsemblToSymbolMapper


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
