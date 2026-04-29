from processing.preprocessing import GeneSymbolNormalizer


def test_human_direct_symbol(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.resolve("BRCA1", "human") == "BRCA1"
    assert normalizer.resolve("MATR3", "human") == "MATR3"


def test_human_prev_symbol_alias(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.resolve("DEC1", "human") == "DELEC1"
    assert normalizer.resolve("SEPT9", "human") == "SEPTIN9"
    assert normalizer.resolve("MARCH1", "human") == "MARCHF1"
    assert normalizer.resolve("GATD3", "human") == "GATD3A"


def test_human_alias_symbol(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.resolve("FLJ20668", "human") == "MARCHF1"
    assert normalizer.resolve("CTS9", "human") == "DELEC1"


def test_human_unknown(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.resolve("NOT_A_GENE", "human") is None


def test_resolve_hgnc_id(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.resolve_hgnc_id("HGNC:18790") == "GATD3A"
    assert normalizer.resolve_hgnc_id("HGNC:1100") == "BRCA1"
    assert normalizer.resolve_hgnc_id("HGNC:99999999") is None


def test_is_symbol(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.is_symbol("BRCA1", "human") is True
    assert normalizer.is_symbol("DEC1", "human") is False  # alias, not approved
    assert normalizer.is_symbol("Slc30a3", "mouse") is True


def test_mouse_direct_symbol(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.resolve("Slc30a3", "mouse") == "Slc30a3"
    assert normalizer.resolve("Trp53", "mouse") == "Trp53"


def test_mouse_withdrawn_alias(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.resolve("p53", "mouse") == "Trp53"


def test_mouse_synonym(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.resolve("Mtap1", "mouse") == "Mtap"


def test_mouse_case_insensitive_fallback(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.resolve("slc30a3", "mouse") == "Slc30a3"
    assert normalizer.resolve("SLC30A3", "mouse") == "Slc30a3"


def test_mouse_unknown(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.resolve("Gm99999", "mouse") is None


def test_empty_input_returns_none(normalizer: GeneSymbolNormalizer) -> None:
    assert normalizer.resolve("", "human") is None
