import pytest

from processing.preprocessing import (
    NON_SYMBOL_CATEGORIES,
    GencodeCloneIndex,
    GeneSymbolNormalizer,
    excel_demangle,
    is_non_symbol_identifier,
    resolve_gencode_clone,
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
        # New GENCODE-clone prefixes seen in polygenic-risk-20 / psychscreen
        # supplementary tables.
        ("ABC7-42389800N19.1", "gencode_clone"),
        ("EM:AC006547.7", "gencode_clone"),
        ("yR211F11.2", "gencode_clone"),
        ("XX-DJ76P10__A.2", "gencode_clone"),
        ("XX-FW80269A6.1", "gencode_clone"),
        ("CITF22-49D8.1", "gencode_clone"),
        ("GHc-602D8.2", "gencode_clone"),
        ("SC22CB-1E7.1", "gencode_clone"),
        ("bP-21201H5.1", "gencode_clone"),
        ("KC877982", "genbank_accession"),
        ("L29074.1", "genbank_accession"),
        # RNA-family labels — Y_RNA / U-snRNA / snoRNA / miRNA / SRP /
        # 7SK / Vault. Family annotations, not loci; should NOT
        # become individual central_gene stubs.
        ("Y_RNA", "rna_family"),
        ("U3", "rna_family"),
        ("U6", "rna_family"),
        ("U7", "rna_family"),
        ("snoU13", "rna_family"),
        ("snoU109", "rna_family"),
        ("snoU2-30", "rna_family"),
        ("snoU2_19", "rna_family"),
        ("SNORA2", "rna_family"),
        ("SNORA7", "rna_family"),
        ("SNORA73", "rna_family"),
        ("SNORA74", "rna_family"),
        ("SNORD42", "rna_family"),
        ("SNORD45", "rna_family"),
        ("SNORD58", "rna_family"),
        ("SNORD59", "rna_family"),
        ("SNORD115", "rna_family"),
        ("SNORD116", "rna_family"),
        ("Metazoa_SRP", "rna_family"),
        ("7SK", "rna_family"),
        ("Vault", "rna_family"),
        ("MIR5096", "rna_family"),
        ("MIR1254-1", "rna_family"),
        ("MIR1273F", "rna_family"),
        ("MIR3687", "rna_family"),
        ("MIR4459", "rna_family"),
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
# NON_SYMBOL_CATEGORIES (predicate map exposed for the YAML loader)
# ---------------------------------------------------------------------------


def test_non_symbol_categories_keys_match_literal() -> None:
    assert set(NON_SYMBOL_CATEGORIES) == {
        "ensembl_human",
        "ensembl_mouse",
        "contig",
        "gencode_clone",
        "genbank_accession",
        "rna_family",
    }


def test_non_symbol_categories_predicate_only_matches_own_category() -> None:
    assert NON_SYMBOL_CATEGORIES["ensembl_human"]("ENSG00000123456") is True
    assert NON_SYMBOL_CATEGORIES["ensembl_human"]("ENSMUSG00000071265") is False
    assert NON_SYMBOL_CATEGORIES["ensembl_mouse"]("ENSMUSG00000071265") is True
    assert NON_SYMBOL_CATEGORIES["genbank_accession"]("KC877982") is True
    assert NON_SYMBOL_CATEGORIES["genbank_accession"]("BRCA1") is False
    assert NON_SYMBOL_CATEGORIES["gencode_clone"]("RP11-783K16.5") is True
    assert NON_SYMBOL_CATEGORIES["rna_family"]("Y_RNA") is True
    assert NON_SYMBOL_CATEGORIES["rna_family"]("MIR5096") is True
    assert NON_SYMBOL_CATEGORIES["rna_family"]("BRCA1") is False
    # rna_family must take precedence over gencode_clone for things like
    # MIR1254-1 (otherwise the hyphen-digit suffix would route it to clone).
    assert NON_SYMBOL_CATEGORIES["rna_family"]("MIR1254-1") is True
    assert NON_SYMBOL_CATEGORIES["gencode_clone"]("MIR1254-1") is False


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


@pytest.mark.parametrize(
    "name",
    [
        # Per the comment thread on #124: GENCODE clone names contain a
        # legitimate `.N` suffix as part of the locus identifier (the
        # ".5" in RP11-783K16.5 is *not* an R make.unique duplicate).
        # The C2 helper must never strip it. The library-level guard
        # protects against this because the un-suffixed form
        # ("RP11-783K16") is also not a known symbol — but the
        # combination is the exact regression we need to pin.
        "RP11-783K16.5",
        "CTD-2331H12.4",
        "KB-1239A14.2",
        "LL0XNC01-7P3.1",
        "XXbac-BPG252P9.10",
    ],
)
def test_strip_make_unique_does_not_corrupt_gencode_clones(
    normalizer: GeneSymbolNormalizer, name: str
) -> None:
    assert strip_make_unique_suffix(name, normalizer) is None


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


# ---------------------------------------------------------------------------
# resolve_gencode_clone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("RP11-100A1.1", ("hgnc_symbol", "BRCA1")),
        ("RP11-200B2.2", ("hgnc_symbol", "MATR3")),
        ("RP11-300C3.3", ("current_ensg", "ENSG00000999991")),
        ("CTD-444D4.4", ("current_ensg", "ENSG00000999992")),
        ("RP11-555E5.5", ("current_ac_accession", "AC012345.6")),
        ("KB-666F6.6", ("current_ac_accession", "AL987654.3")),
    ],
)
def test_resolve_gencode_clone_positive(
    gencode_clone_index: GencodeCloneIndex,
    name: str,
    expected: tuple[str, str],
) -> None:
    assert resolve_gencode_clone(name, gencode_clone_index) == expected


@pytest.mark.parametrize(
    "name",
    [
        "BRCA1",                       # real symbol — not a clone
        "RP11-NOT-IN-INDEX.1",         # clone-shaped but unknown
        "ENSG00000123456",             # ENSG, not a clone
        "",                            # empty
    ],
)
def test_resolve_gencode_clone_negative(
    gencode_clone_index: GencodeCloneIndex,
    name: str,
) -> None:
    assert resolve_gencode_clone(name, gencode_clone_index) is None


def test_gencode_clone_index_from_paths_loads_all_kinds(
    gencode_clone_index: GencodeCloneIndex,
) -> None:
    # Sanity check on the loader: all six fixture rows make it in, with
    # the right kinds, and lookup works for every one.
    assert len(gencode_clone_index.clone_to_status) == 6
    kinds = {kind for kind, _ in gencode_clone_index.clone_to_status.values()}
    assert kinds == {"hgnc_symbol", "current_ensg", "current_ac_accession"}
