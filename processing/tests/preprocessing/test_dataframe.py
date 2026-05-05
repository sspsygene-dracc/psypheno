import pandas as pd
import pytest

from processing.preprocessing import (
    EnsemblToSymbolMapper,
    GencodeCloneIndex,
    GeneSymbolNormalizer,
    clean_gene_column,
)


def test_clean_gene_column_full_pipeline(normalizer: GeneSymbolNormalizer) -> None:
    df = pd.DataFrame(
        {
            "target_gene": [
                "BRCA1",          # passed_through
                "DEC1",           # passed_through (alias → DELEC1)
                "9-Sep",          # rescued_excel
                "2023-09-04",     # rescued_excel
                "MATR3.1",        # rescued_make_unique
                "TBCE_ENSG00000284770",  # rescued_symbol_ensg
                "ENSG00000123456",  # non_symbol_ensembl_human
                "RP11-783K16.5",  # non_symbol_gencode_clone
                "WHO_KNOWS",      # unresolved
                "",               # passed_through (empty)
            ],
            "extra": list(range(10)),
        }
    )
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        excel_demangle=True,
        strip_make_unique=True,
        split_symbol_ensg=True,
    )

    assert out["target_gene"].tolist() == [
        "BRCA1",
        "DELEC1",
        "SEPTIN9",
        "SEPTIN4",
        "MATR3",
        "TBCE",
        "ENSG00000123456",
        "RP11-783K16.5",
        "WHO_KNOWS",
        "",
    ]
    assert report.resolutions == [
        "passed_through",
        "passed_through",
        "rescued_excel",
        "rescued_excel",
        "rescued_make_unique",
        "rescued_symbol_ensg",
        "non_symbol_ensembl_human",
        "non_symbol_gencode_clone",
        "unresolved",
        "passed_through",
    ]
    assert report.dropped_indices == []
    assert "extra" in out.columns
    assert "_target_gene_resolution" in out.columns


def test_clean_gene_column_drop_non_symbols(
    normalizer: GeneSymbolNormalizer,
) -> None:
    df = pd.DataFrame(
        {
            "target_gene": ["BRCA1", "ENSG00000123456", "MATR3"],
        }
    )
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        drop_non_symbols=True,
    )
    assert out["target_gene"].tolist() == ["BRCA1", "MATR3"]
    assert report.dropped_indices == [1]


def test_clean_gene_column_resolve_hgnc_id(
    normalizer: GeneSymbolNormalizer,
) -> None:
    df = pd.DataFrame(
        {
            "hgnc_symbol": [
                "BRCA1",         # passed_through
                "HGNC:18790",    # rescued_hgnc_id -> GATD3A
                "HGNC:1100",     # rescued_hgnc_id -> BRCA1
                "HGNC:99999999", # unresolved (no such HGNC id in fixtures)
                "HGNC:notnumeric",  # unresolved (not a real HGNC id)
            ],
        }
    )
    out, report = clean_gene_column(
        df,
        "hgnc_symbol",
        species="human",
        normalizer=normalizer,
        resolve_hgnc_id=True,
    )
    assert out["hgnc_symbol"].tolist() == [
        "BRCA1",
        "GATD3A",
        "BRCA1",
        "HGNC:99999999",
        "HGNC:notnumeric",
    ]
    assert report.resolutions == [
        "passed_through",
        "rescued_hgnc_id",
        "rescued_hgnc_id",
        "unresolved",
        "unresolved",
    ]


def test_clean_gene_column_resolve_hgnc_id_on_by_default(
    normalizer: GeneSymbolNormalizer,
) -> None:
    # Defaults are opt-out: HGNC:NNNNN values resolve without the
    # caller having to flip a flag.
    df = pd.DataFrame({"hgnc_symbol": ["HGNC:18790"]})
    out, report = clean_gene_column(
        df, "hgnc_symbol", species="human", normalizer=normalizer
    )
    assert out["hgnc_symbol"].tolist() == ["GATD3A"]
    assert report.resolutions == ["rescued_hgnc_id"]


def test_clean_gene_column_resolve_hgnc_id_can_opt_out(
    normalizer: GeneSymbolNormalizer,
) -> None:
    # Wranglers can disable a specific resolver by passing False.
    df = pd.DataFrame({"hgnc_symbol": ["HGNC:18790"]})
    out, report = clean_gene_column(
        df,
        "hgnc_symbol",
        species="human",
        normalizer=normalizer,
        resolve_hgnc_id=False,
    )
    assert out["hgnc_symbol"].tolist() == ["HGNC:18790"]
    assert report.resolutions == ["unresolved"]


def test_clean_gene_column_summary_string(
    normalizer: GeneSymbolNormalizer,
) -> None:
    df = pd.DataFrame({"target_gene": ["BRCA1", "9-Sep", "WHO_KNOWS"]})
    _, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        excel_demangle=True,
    )
    s = report.summary()
    assert "passed-through 1" in s
    assert "rescued 1" in s
    assert "unresolved 1" in s


def test_clean_gene_column_preserves_raw(
    normalizer: GeneSymbolNormalizer,
) -> None:
    # The raw, pre-cleaner value MUST land in `<col>_raw` so wranglers
    # can audit each row from the cleaned TSV alone.
    df = pd.DataFrame(
        {"target_gene": ["BRCA1", "9-Sep", "MATR3.1", "WHO_KNOWS", ""]}
    )
    out, _ = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        excel_demangle=True,
        strip_make_unique=True,
    )
    assert out["target_gene_raw"].tolist() == [
        "BRCA1",
        "9-Sep",
        "MATR3.1",
        "WHO_KNOWS",
        "",
    ]
    assert out["target_gene"].tolist() == [
        "BRCA1",
        "SEPTIN9",
        "MATR3",
        "WHO_KNOWS",
        "",
    ]


def test_clean_gene_column_raw_collision_raises(
    normalizer: GeneSymbolNormalizer,
) -> None:
    df = pd.DataFrame(
        {"target_gene": ["BRCA1"], "target_gene_raw": ["already-here"]}
    )
    with pytest.raises(KeyError, match="target_gene_raw"):
        clean_gene_column(
            df, "target_gene", species="human", normalizer=normalizer
        )


def test_clean_gene_column_manual_aliases(
    normalizer: GeneSymbolNormalizer,
) -> None:
    # NOV is ambiguous in HGNC alias_to_symbol (CCN3 prev, RPL10 alias,
    # PLXNA1 alias) so the normalizer drops it. A wrangler-supplied
    # manual_alias maps it to CCN3 explicitly. Tagged
    # `rescued_manual_alias` and verified via the normalizer.
    df = pd.DataFrame(
        {
            "target_gene": [
                "BRCA1",       # passed_through
                "QARS",        # rescued_manual_alias -> QARS1 (if available)
                "BRCA1",       # passed_through
            ]
        }
    )
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        manual_aliases={"QARS": "BRCA1"},  # use BRCA1 as the rescue target
                                            # since fixtures don't include QARS1
    )
    assert out["target_gene"].tolist() == ["BRCA1", "BRCA1", "BRCA1"]
    assert out["target_gene_raw"].tolist() == ["BRCA1", "QARS", "BRCA1"]
    assert report.resolutions == [
        "passed_through",
        "rescued_manual_alias",
        "passed_through",
    ]
    assert report.counts["rescued_manual_alias"] == 1


def test_clean_gene_column_manual_aliases_unresolvable_target_raises(
    normalizer: GeneSymbolNormalizer,
) -> None:
    df = pd.DataFrame({"target_gene": ["NOV"]})
    with pytest.raises(ValueError, match="manual_aliases.*NOTAREALSYMBOL"):
        clean_gene_column(
            df,
            "target_gene",
            species="human",
            normalizer=normalizer,
            manual_aliases={"NOV": "NOTAREALSYMBOL"},
        )


def test_clean_gene_column_resolve_via_ensembl_map(
    normalizer: GeneSymbolNormalizer,
    ensembl_mapper: EnsemblToSymbolMapper,
) -> None:
    df = pd.DataFrame(
        {
            "target_gene": [
                "BRCA1",                  # passed_through
                "ENSG00000160221",        # rescued_ensembl_map -> GATD3A
                "ENSG00000012048.4",      # rescued_ensembl_map -> BRCA1 (versioned)
                "ENSG99999999999",        # non_symbol_ensembl_human (orphan)
            ]
        }
    )
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        ensembl_mapper=ensembl_mapper,
        resolve_via_ensembl_map=True,
    )
    assert out["target_gene"].tolist() == [
        "BRCA1",
        "GATD3A",
        "BRCA1",
        "ENSG99999999999",
    ]
    assert report.resolutions == [
        "passed_through",
        "rescued_ensembl_map",
        "rescued_ensembl_map",
        "non_symbol_ensembl_human",
    ]
    assert report.counts["rescued_ensembl_map"] == 2


def test_clean_gene_column_resolve_via_ensembl_map_mouse(
    normalizer: GeneSymbolNormalizer,
    ensembl_mapper: EnsemblToSymbolMapper,
) -> None:
    df = pd.DataFrame(
        {
            "marker_ensembl_id": [
                "Slc30a3",                # passed_through
                "ENSMUSG00000029151",     # rescued_ensembl_map -> Slc30a3
                "ENSMUSG99999999999",     # non_symbol_ensembl_mouse (orphan)
            ]
        }
    )
    out, report = clean_gene_column(
        df,
        "marker_ensembl_id",
        species="mouse",
        normalizer=normalizer,
        ensembl_mapper=ensembl_mapper,
        resolve_via_ensembl_map=True,
    )
    assert out["marker_ensembl_id"].tolist() == [
        "Slc30a3",
        "Slc30a3",
        "ENSMUSG99999999999",
    ]
    assert report.resolutions == [
        "passed_through",
        "rescued_ensembl_map",
        "non_symbol_ensembl_mouse",
    ]


def test_clean_gene_column_resolve_via_ensembl_map_silent_skip_no_mapper(
    normalizer: GeneSymbolNormalizer,
) -> None:
    # When no ensembl_mapper is supplied, the resolver silently skips
    # rather than raising — so the lower-level API stays callable from
    # tests / one-off scripts that only want symbol normalization.
    df = pd.DataFrame({"target_gene": ["BRCA1", "ENSG00000012048"]})
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        # resolve_via_ensembl_map defaults to True; mapper omitted.
    )
    assert out["target_gene"].tolist() == ["BRCA1", "ENSG00000012048"]
    # ENSG falls through to the silencer (no mapper to rescue it).
    assert report.resolutions == ["passed_through", "non_symbol_ensembl_human"]


def test_clean_gene_column_resolve_via_ensembl_map_runs_after_auto_rescues(
    normalizer: GeneSymbolNormalizer,
    ensembl_mapper: EnsemblToSymbolMapper,
) -> None:
    # Direct symbols win over the ENSG rescue path; this ensures the
    # ensembl rescue does not eclipse the normalizer's own work.
    df = pd.DataFrame({"target_gene": ["BRCA1", "DEC1"]})
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        ensembl_mapper=ensembl_mapper,
        resolve_via_ensembl_map=True,
    )
    assert out["target_gene"].tolist() == ["BRCA1", "DELEC1"]
    assert report.resolutions == ["passed_through", "passed_through"]


def test_clean_gene_column_manual_aliases_runs_after_auto_rescues(
    normalizer: GeneSymbolNormalizer,
) -> None:
    # If a value is already rescuable by an earlier helper (e.g.
    # excel_demangle picks up `9-Sep`), the auto-rescue wins; the manual
    # alias is a last-resort fallback only.
    df = pd.DataFrame({"target_gene": ["9-Sep"]})
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        excel_demangle=True,
        manual_aliases={"9-Sep": "BRCA1"},
    )
    assert out["target_gene"].tolist() == ["SEPTIN9"]
    assert report.resolutions == ["rescued_excel"]


# ---------------------------------------------------------------------------
# resolve_gencode_clone
# ---------------------------------------------------------------------------


def test_clean_gene_column_resolve_gencode_clone(
    normalizer: GeneSymbolNormalizer,
    gencode_clone_index: GencodeCloneIndex,
) -> None:
    df = pd.DataFrame(
        {
            "target_gene": [
                "BRCA1",            # passed_through (real symbol)
                "RP11-100A1.1",     # rescued_gencode_clone_hgnc_symbol -> BRCA1
                "RP11-300C3.3",     # rescued_gencode_clone_current_ensg
                "RP11-555E5.5",     # rescued_gencode_clone_current_ac_accession
                "RP11-NOPE-XYZ.9",  # falls through to non_symbol_gencode_clone
            ]
        }
    )
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        gencode_clone_index=gencode_clone_index,
        resolve_gencode_clone=True,
    )
    assert out["target_gene"].tolist() == [
        "BRCA1",
        "BRCA1",
        "ENSG00000999991",
        "AC012345.6",
        "RP11-NOPE-XYZ.9",
    ]
    assert report.resolutions == [
        "passed_through",
        "rescued_gencode_clone_hgnc_symbol",
        "rescued_gencode_clone_current_ensg",
        "rescued_gencode_clone_current_ac_accession",
        "non_symbol_gencode_clone",
    ]


def test_clean_gene_column_resolve_gencode_clone_silent_skip_no_index(
    normalizer: GeneSymbolNormalizer,
) -> None:
    # When no gencode_clone_index is supplied, the resolver silently
    # skips rather than raising — clones fall through to the existing
    # gencode_clone silencer.
    df = pd.DataFrame({"target_gene": ["RP11-100A1.1"]})
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        # resolve_gencode_clone defaults to True; index omitted.
    )
    assert out["target_gene"].tolist() == ["RP11-100A1.1"]
    assert report.resolutions == ["non_symbol_gencode_clone"]


def test_clean_gene_column_resolve_gencode_clone_ordering(
    normalizer: GeneSymbolNormalizer,
    gencode_clone_index: GencodeCloneIndex,
) -> None:
    # Ordering invariant: a real symbol that happens to also be in the
    # clone TSV (shouldn't happen in practice, but the guard is the
    # initial `normalizer.resolve()` short-circuit at the top of the
    # per-row loop) wins over the clone index.
    df = pd.DataFrame({"target_gene": ["BRCA1"]})
    out, report = clean_gene_column(
        df,
        "target_gene",
        species="human",
        normalizer=normalizer,
        gencode_clone_index=gencode_clone_index,
        resolve_gencode_clone=True,
    )
    assert out["target_gene"].tolist() == ["BRCA1"]
    assert report.resolutions == ["passed_through"]
