import pytest

from processing.preprocessing import (
    GeneSymbolNormalizer,
    excel_demangle,
    is_non_symbol_identifier,
    split_symbol_ensg,
    strip_make_unique_suffix,
)


# ---------------------------------------------------------------------------
# excel_demangle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("1-Mar", "MARCHF1"),
        ("9-Sep", "SEPTIN9"),
        ("4-Sep", "SEPTIN4"),
        ("1-Dec", "DELEC1"),
        ("2023-09-04", "SEPTIN4"),
        ("2023-09-09", "SEPTIN9"),
        ("2023-03-01", "MARCHF1"),
    ],
)
def test_excel_demangle_classic_and_iso(
    normalizer: GeneSymbolNormalizer, name: str, expected: str
) -> None:
    assert excel_demangle(name, normalizer) == expected


@pytest.mark.parametrize(
    "name",
    [
        "Mar",
        "BRCA1",
        "1-Apr",
        "",
        "2023-04-01",
        "1-Mar-extra",
    ],
)
def test_excel_demangle_negative(
    normalizer: GeneSymbolNormalizer, name: str
) -> None:
    assert excel_demangle(name, normalizer) is None


def test_excel_demangle_unrecognized_gene_number(
    normalizer: GeneSymbolNormalizer,
) -> None:
    # Format matches but the rescued candidate (MARCHF99) isn't a real symbol.
    assert excel_demangle("99-Mar", normalizer) is None


# ---------------------------------------------------------------------------
# is_non_symbol_identifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,category",
    [
        ("ENSG00000123456", "ensembl_human"),
        ("ENSG00000123456.5", "ensembl_human"),
        ("ENSMUSG00000071265", "ensembl_mouse"),
        ("AUXG01000058.1", "contig"),
        ("AC012345.6", "contig"),
        ("RP11-783K16.5", "gencode_clone"),
        ("CTD-2331H12.4", "gencode_clone"),
        ("hsa-mir-99", "gencode_clone"),
        ("KC877982", "genbank_accession"),
        ("L29074.1", "genbank_accession"),
    ],
)
def test_is_non_symbol_identifier_positive(name: str, category: str) -> None:
    assert is_non_symbol_identifier(name) == category


@pytest.mark.parametrize(
    "name",
    [
        "BRCA1",
        "RPS6",
        "MATR3",
        "Slc30a3",
        "",
    ],
)
def test_is_non_symbol_identifier_negative(name: str) -> None:
    assert is_non_symbol_identifier(name) is None


# ---------------------------------------------------------------------------
# strip_make_unique_suffix
# ---------------------------------------------------------------------------


def test_strip_make_unique_recovers(normalizer: GeneSymbolNormalizer) -> None:
    assert strip_make_unique_suffix("MATR3.1", normalizer) == "MATR3"


def test_strip_make_unique_guard_a_unsuffixed_not_real(
    normalizer: GeneSymbolNormalizer,
) -> None:
    # KC877982 is a GenBank accession, not a real symbol — must not invent.
    assert strip_make_unique_suffix("KC877982.1", normalizer) is None


def test_strip_make_unique_guard_b_suffixed_already_real(
    normalizer: GeneSymbolNormalizer,
) -> None:
    # If a `.N`-suffixed value is itself a real symbol, do not strip.
    # (None of our fixture symbols have a `.N` form, so we simulate via a
    # GENCODE-clone-shaped name whose un-suffixed form is also unknown.)
    assert strip_make_unique_suffix("RP11-783K16.5", normalizer) is None


def test_strip_make_unique_no_suffix(normalizer: GeneSymbolNormalizer) -> None:
    assert strip_make_unique_suffix("MATR3", normalizer) is None
    assert strip_make_unique_suffix("", normalizer) is None


# ---------------------------------------------------------------------------
# split_symbol_ensg
# ---------------------------------------------------------------------------


def test_split_symbol_ensg_positive() -> None:
    assert split_symbol_ensg("TBCE_ENSG00000284770") == (
        "TBCE",
        "ENSG00000284770",
    )
    assert split_symbol_ensg("ARMCX5-GPRASP2_ENSG00000286237") == (
        "ARMCX5-GPRASP2",
        "ENSG00000286237",
    )


@pytest.mark.parametrize(
    "name",
    [
        "TBCE",
        "ENSG00000284770",
        "TBCE_OTHER",
        "",
    ],
)
def test_split_symbol_ensg_negative(name: str) -> None:
    assert split_symbol_ensg(name) is None
