import logging
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from processing import central_gene_table as cgt_module
from processing.central_gene_table import CentralGeneTable, CentralGeneTableEntry
from processing.types.gene_mapping import GeneMapping, NonResolving


# ---------------------------------------------------------------------------
# NonResolving.from_json + classify
# ---------------------------------------------------------------------------


def test_non_resolving_empty() -> None:
    nr = NonResolving.from_json({})
    assert nr.classify("BRCA1") == "fallback"


def test_non_resolving_control_values() -> None:
    nr = NonResolving.from_json({"control_values": ["GFP", "NonTarget1"]})
    assert nr.classify("GFP") == "control"
    assert nr.classify("NonTarget1") == "control"
    assert nr.classify("BRCA1") == "fallback"


def test_non_resolving_record_values() -> None:
    nr = NonResolving.from_json({"record_values": ["SGK494", "GATD3B"]})
    assert nr.classify("SGK494") == "record"
    assert nr.classify("GATD3B") == "record"
    assert nr.classify("BRCA1") == "fallback"


def test_non_resolving_record_patterns() -> None:
    nr = NonResolving.from_json({"record_patterns": ["genbank_accession", "contig"]})
    assert nr.classify("KC877982") == "record"
    assert nr.classify("AC012345.6") == "record"
    assert nr.classify("BRCA1") == "fallback"


def test_non_resolving_auto_records_non_symbol_shapes() -> None:
    # Empty NonResolving still auto-silences any value classified by
    # is_non_symbol_identifier (ENSG / clone / contig / RNA family /
    # GenBank). Datasets no longer need to add record_patterns to
    # silence load-db warnings about these built-in shapes.
    nr = NonResolving.from_json({})
    assert nr.classify("ENSG00000123456") == "record"
    assert nr.classify("ENSMUSG00000071265") == "record"
    assert nr.classify("RP11-783K16.5") == "record"
    assert nr.classify("AC012345.6") == "record"
    assert nr.classify("KC877982") == "record"
    assert nr.classify("Y_RNA") == "record"
    assert nr.classify("MIR5096") == "record"
    # Real symbols still fall through to the strict default.
    assert nr.classify("BRCA1") == "fallback"
    assert nr.classify("MATR3") == "fallback"


def test_non_resolving_unknown_pattern_raises() -> None:
    with pytest.raises(ValueError, match="Unknown non_resolving pattern category"):
        NonResolving.from_json({"record_patterns": ["not_a_category"]})


def test_non_resolving_drop_values_retired() -> None:
    with pytest.raises(ValueError, match="no longer supported"):
        NonResolving.from_json({"drop_values": ["GFP"]})


def test_non_resolving_drop_patterns_retired() -> None:
    with pytest.raises(ValueError, match="no longer supported"):
        NonResolving.from_json({"drop_patterns": ["ensembl_human"]})


def test_non_resolving_unknown_key_raises() -> None:
    with pytest.raises(ValueError, match="unknown key"):
        NonResolving.from_json({"control_value": ["GFP"]})  # typo


def test_non_resolving_value_overlap_raises() -> None:
    with pytest.raises(ValueError, match="control_values and record_values"):
        NonResolving.from_json(
            {"control_values": ["X"], "record_values": ["X"]}
        )


# ---------------------------------------------------------------------------
# GeneMapping.from_json
# ---------------------------------------------------------------------------


def _base_mapping() -> dict[str, Any]:
    return {
        "column_name": "target_gene",
        "species": "human",
        "link_table_name": "gene",
        "perturbed_or_target": "target",
    }


def test_gene_mapping_minimal() -> None:
    gm = GeneMapping.from_json(_base_mapping())
    assert gm.column_name == "target_gene"
    assert gm.non_resolving.classify("anything") == "fallback"


def test_gene_mapping_with_non_resolving() -> None:
    cfg = _base_mapping()
    cfg["non_resolving"] = {
        "control_values": ["GFP"],
        "record_values": ["SGK494"],
    }
    gm = GeneMapping.from_json(cfg)
    assert gm.non_resolving.classify("GFP") == "control"
    assert gm.non_resolving.classify("SGK494") == "record"


def test_gene_mapping_rejects_ignore_missing() -> None:
    cfg = _base_mapping()
    cfg["ignore_missing"] = ["NOV"]
    with pytest.raises(ValueError, match="no longer supported"):
        GeneMapping.from_json(cfg)


def test_gene_mapping_rejects_replace() -> None:
    cfg = _base_mapping()
    cfg["replace"] = {"X": "Y"}
    with pytest.raises(ValueError, match="no longer supported"):
        GeneMapping.from_json(cfg)


def test_gene_mapping_rejects_to_upper() -> None:
    cfg = _base_mapping()
    cfg["to_upper"] = True
    with pytest.raises(ValueError, match="no longer supported"):
        GeneMapping.from_json(cfg)


def test_gene_mapping_rejects_legacy_perturbed_field() -> None:
    cfg = _base_mapping()
    cfg["is_perturbed"] = True
    del cfg["perturbed_or_target"]
    with pytest.raises(ValueError, match="legacy fields"):
        GeneMapping.from_json(cfg)


# ---------------------------------------------------------------------------
# resolve_to_central_gene_table — dispatch order, link-table asymmetry fix
# ---------------------------------------------------------------------------


@pytest.fixture
def central_gene_stub(monkeypatch: pytest.MonkeyPatch) -> CentralGeneTable:
    """Replace the singleton with a fresh, pre-seeded CentralGeneTable.

    Seeds one human entry (BRCA1) so the species_map has a hit. All
    `add_species_entry` calls land in the same table so the test can
    assert how many stubs were created.
    """
    table = CentralGeneTable()
    table.entries.append(
        CentralGeneTableEntry(
            row_id=0,
            human_symbol="BRCA1",
            human_entrez_gene=None,
            human_ensembl_gene=None,
            hgnc_id=None,
            mouse_symbols=set(),
            mouse_mgi_accession_ids=set(),
            mouse_ensembl_genes=set(),
            human_synonyms=set(),
            mouse_synonyms=set(),
        )
    )
    monkeypatch.setattr(cgt_module, "_CENTRAL_GENE_TABLE", table)
    # gene_mapping.py imports get_central_gene_table from
    # processing.central_gene_table; patching the module-level singleton
    # is sufficient since get_central_gene_table reads it on each call.
    return table


def test_link_table_asymmetry_first_encounter_is_linked(
    central_gene_stub: CentralGeneTable,
) -> None:
    # Before the fix: the FIRST row with a never-seen unresolved symbol
    # got `add_species_entry` but no `(row_id, entry.row_id)` append.
    # After the fix: every row, including the first, gets linked.
    cfg = _base_mapping()
    cfg["non_resolving"] = {"record_values": ["WEIRDGENE"]}
    df = pd.DataFrame(
        {"id": [10, 20, 30], "target_gene": ["WEIRDGENE", "WEIRDGENE", "BRCA1"]}
    )
    gm = GeneMapping.from_json(cfg)
    link = gm.resolve_to_central_gene_table("t", df, Path("/dev/null"))
    # Every row gets a non-None central_gene_id — first WEIRDGENE row is
    # NOT orphaned.
    assert all(cg_id is not None for _, cg_id in link.central_gene_table_links)
    # WEIRDGENE rows share the same stub.
    weirdgene_links = [
        cg for rid, cg in link.central_gene_table_links if rid in (10, 20)
    ]
    assert len(set(weirdgene_links)) == 1
    # Only one stub created (not duplicated).
    assert len(central_gene_stub.entries) == 2  # BRCA1 + WEIRDGENE


def test_dispatch_control_values_creates_kind_control_stub(
    central_gene_stub: CentralGeneTable,
) -> None:
    cfg = _base_mapping()
    cfg["non_resolving"] = {"control_values": ["GFP"]}
    df = pd.DataFrame({"id": [1], "target_gene": ["GFP"]})
    gm = GeneMapping.from_json(cfg)
    link = gm.resolve_to_central_gene_table("t", df, Path("/dev/null"))
    [(row_id, cg_id)] = link.central_gene_table_links
    assert row_id == 1
    assert cg_id is not None
    # Control stub is created with kind='control' so per-gene aggregates
    # can filter it out.
    new_entry = central_gene_stub.entries[cg_id]
    assert new_entry.kind == "control"
    assert new_entry.manually_added is True
    assert new_entry.human_symbol == "GFP"


def test_dispatch_record_values_creates_stub(
    central_gene_stub: CentralGeneTable,
) -> None:
    cfg = _base_mapping()
    cfg["non_resolving"] = {"record_values": ["SGK494"]}
    df = pd.DataFrame({"id": [1], "target_gene": ["SGK494"]})
    gm = GeneMapping.from_json(cfg)
    link = gm.resolve_to_central_gene_table("t", df, Path("/dev/null"))
    [(row_id, cg_id)] = link.central_gene_table_links
    assert row_id == 1
    assert cg_id is not None
    # Stub is `manually_added=True`, kind='gene' (not a control).
    new_entry = central_gene_stub.entries[cg_id]
    assert new_entry.manually_added is True
    assert new_entry.kind == "gene"
    assert new_entry.human_symbol == "SGK494"


def _fallback_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == "sspsygene_logger" and r.levelno == logging.WARNING
    ]


def test_dispatch_fallback_warns_and_records(
    central_gene_stub: CentralGeneTable,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # No non_resolving entry covers WEIRDGENE → fallback path: aggregated
    # warn + create stub + link.
    caplog.set_level(logging.WARNING, logger="sspsygene_logger")
    cfg = _base_mapping()
    df = pd.DataFrame({"id": [1], "target_gene": ["WEIRDGENE"]})
    gm = GeneMapping.from_json(cfg)
    link = gm.resolve_to_central_gene_table("t", df, Path("/tmp/in.csv"))
    [(_, cg_id)] = link.central_gene_table_links
    assert cg_id is not None
    assert central_gene_stub.entries[cg_id].human_symbol == "WEIRDGENE"
    assert central_gene_stub.entries[cg_id].manually_added is True

    [warning] = _fallback_warnings(caplog)
    assert "t.target_gene" in warning.message
    assert "in.csv" in warning.message
    assert "1/1 rows (100.0%)" in warning.message
    assert "WEIRDGENE" in warning.message


def test_fallback_aggregates_per_column(
    central_gene_stub: CentralGeneTable,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 100 rows, 5 distinct unresolvable values (counts: 1, 1, 1, 1, 1) →
    # 5/100 affected = 5%. Exactly one aggregate warning.
    caplog.set_level(logging.WARNING, logger="sspsygene_logger")
    df = pd.DataFrame(
        {
            "id": list(range(100)),
            "target_gene": ["BRCA1"] * 95
            + ["WEIRD1", "WEIRD2", "WEIRD3", "WEIRD4", "WEIRD1"],
        }
    )
    gm = GeneMapping.from_json(_base_mapping())
    gm.resolve_to_central_gene_table("ds", df, Path("/tmp/in.csv"))

    [warning] = _fallback_warnings(caplog)
    assert "ds.target_gene" in warning.message
    assert "5/100 rows (5.0%)" in warning.message
    # Most-common value first; WEIRD1 appears twice.
    assert "WEIRD1 (x2)" in warning.message


def test_fallback_under_threshold_no_ansi(
    central_gene_stub: CentralGeneTable,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="sspsygene_logger")
    df = pd.DataFrame(
        {
            "id": list(range(100)),
            "target_gene": ["BRCA1"] * 98 + ["WEIRD1", "WEIRD2"],
        }
    )
    gm = GeneMapping.from_json(_base_mapping())
    gm.resolve_to_central_gene_table("ds", df, Path("/tmp/in.csv"))

    [warning] = _fallback_warnings(caplog)
    # 2/100 = 2.0% which is <= 3% → plain text, no ANSI escape.
    assert "2/100 rows (2.0%)" in warning.message
    assert "\x1b[" not in warning.message


def test_fallback_over_threshold_uses_red_bold_ansi(
    central_gene_stub: CentralGeneTable,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="sspsygene_logger")
    df = pd.DataFrame(
        {
            "id": list(range(100)),
            "target_gene": ["BRCA1"] * 90 + [f"WEIRD{i}" for i in range(10)],
        }
    )
    gm = GeneMapping.from_json(_base_mapping())
    gm.resolve_to_central_gene_table("ds", df, Path("/tmp/in.csv"))

    [warning] = _fallback_warnings(caplog)
    # 10/100 = 10% > 3% → click.style emits ANSI.
    assert "10/100 rows (10.0%)" in warning.message
    assert "\x1b[" in warning.message


def test_fallback_sample_capped_at_10(
    central_gene_stub: CentralGeneTable,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="sspsygene_logger")
    # 12 distinct unresolvable values, each appearing once.
    weird = [f"WEIRD{i}" for i in range(12)]
    df = pd.DataFrame(
        {
            "id": list(range(100)),
            "target_gene": ["BRCA1"] * 88 + weird,
        }
    )
    gm = GeneMapping.from_json(_base_mapping())
    gm.resolve_to_central_gene_table("ds", df, Path("/tmp/in.csv"))

    [warning] = _fallback_warnings(caplog)
    # Only 10 sample entries, then "+2 more".
    assert warning.message.count("(x1)") == 10
    assert "+2 more" in warning.message


def test_multi_gene_separator_counts_row_once(
    central_gene_stub: CentralGeneTable,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # One row, three unresolvable genes inside it. Affected rows = 1, not 3.
    caplog.set_level(logging.WARNING, logger="sspsygene_logger")
    cfg = _base_mapping()
    cfg["multi_gene_separator"] = ","
    df = pd.DataFrame({"id": [0], "target_gene": ["WEIRD1,WEIRD2,WEIRD3"]})
    gm = GeneMapping.from_json(cfg)
    gm.resolve_to_central_gene_table("ds", df, Path("/tmp/in.csv"))

    [warning] = _fallback_warnings(caplog)
    assert "1/1 rows (100.0%)" in warning.message
    # All three values appear in the sample.
    for v in ("WEIRD1", "WEIRD2", "WEIRD3"):
        assert v in warning.message
