from pathlib import Path

import pytest

from processing.preprocessing import GeneSymbolNormalizer


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def normalizer() -> GeneSymbolNormalizer:
    return GeneSymbolNormalizer.from_paths(
        hgnc_file=FIXTURES / "hgnc_stub.txt",
        mgi_file=FIXTURES / "mgi_stub.rpt",
    )
