from processing.preprocessing.ensembl_index import EnsemblToSymbolMapper


def test_human_ensg_resolves_to_symbol(ensembl_mapper: EnsemblToSymbolMapper) -> None:
    assert ensembl_mapper.resolve_ensg("ENSG00000012048", "human") == "BRCA1"
    assert ensembl_mapper.resolve_ensg("ENSG00000160221", "human") == "GATD3A"


def test_human_versioned_ensg_resolves(ensembl_mapper: EnsemblToSymbolMapper) -> None:
    assert ensembl_mapper.resolve_ensg("ENSG00000012048.4", "human") == "BRCA1"
    assert ensembl_mapper.resolve_ensg("ENSG00000160221.12", "human") == "GATD3A"


def test_human_unknown_ensg_returns_none(
    ensembl_mapper: EnsemblToSymbolMapper,
) -> None:
    assert ensembl_mapper.resolve_ensg("ENSG99999999999", "human") is None


def test_mouse_ensmusg_resolves_to_symbol(
    ensembl_mapper: EnsemblToSymbolMapper,
) -> None:
    assert ensembl_mapper.resolve_ensg("ENSMUSG00000029151", "mouse") == "Slc30a3"
    assert ensembl_mapper.resolve_ensg("ENSMUSG00000059552", "mouse") == "Trp53"


def test_mouse_versioned_ensmusg_resolves(
    ensembl_mapper: EnsemblToSymbolMapper,
) -> None:
    assert (
        ensembl_mapper.resolve_ensg("ENSMUSG00000029151.7", "mouse") == "Slc30a3"
    )


def test_mouse_unknown_ensmusg_returns_none(
    ensembl_mapper: EnsemblToSymbolMapper,
) -> None:
    assert ensembl_mapper.resolve_ensg("ENSMUSG99999999999", "mouse") is None


def test_species_isolation(ensembl_mapper: EnsemblToSymbolMapper) -> None:
    # A human ENSG must not resolve under "mouse", and vice versa.
    assert ensembl_mapper.resolve_ensg("ENSG00000012048", "mouse") is None
    assert ensembl_mapper.resolve_ensg("ENSMUSG00000029151", "human") is None


def test_non_ensg_input_returns_none(
    ensembl_mapper: EnsemblToSymbolMapper,
) -> None:
    assert ensembl_mapper.resolve_ensg("BRCA1", "human") is None
    assert ensembl_mapper.resolve_ensg("RP11-783K16.5", "human") is None
    assert ensembl_mapper.resolve_ensg("", "human") is None


def test_map_sizes(ensembl_mapper: EnsemblToSymbolMapper) -> None:
    # Sanity check that both source files were parsed. The HGNC stub has
    # 10 rows but ABALON's ensembl_gene_id is intentionally blank (no real
    # HGNC entry), so 9 human pairs end up in the map.
    assert len(ensembl_mapper.human_ensg_to_symbol) == 9
    assert len(ensembl_mapper.mouse_ensg_to_symbol) == 3
