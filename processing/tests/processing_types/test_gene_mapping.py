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


def test_non_resolving_drop_values() -> None:
    nr = NonResolving.from_json({"drop_values": ["GFP", "NonTarget1"]})
    assert nr.classify("GFP") == "drop"
    assert nr.classify("NonTarget1") == "drop"
    assert nr.classify("BRCA1") == "fallback"


def test_non_resolving_record_values() -> None:
    nr = NonResolving.from_json({"record_values": ["SGK494", "GATD3B"]})
    assert nr.classify("SGK494") == "record"
    assert nr.classify("GATD3B") == "record"
    assert nr.classify("BRCA1") == "fallback"


def test_non_resolving_drop_patterns() -> None:
    nr = NonResolving.from_json({"drop_patterns": ["ensembl_human"]})
    assert nr.classify("ENSG00000123456") == "drop"
    assert nr.classify("ENSMUSG00000071265") == "fallback"
    assert nr.classify("BRCA1") == "fallback"


def test_non_resolving_record_patterns() -> None:
    nr = NonResolving.from_json({"record_patterns": ["genbank_accession", "contig"]})
    assert nr.classify("KC877982") == "record"
    assert nr.classify("AC012345.6") == "record"
    assert nr.classify("BRCA1") == "fallback"


def test_non_resolving_unknown_pattern_raises() -> None:
    with pytest.raises(ValueError, match="Unknown non_resolving pattern category"):
        NonResolving.from_json({"drop_patterns": ["not_a_category"]})


def test_non_resolving_unknown_key_raises() -> None:
    with pytest.raises(ValueError, match="unknown key"):
        NonResolving.from_json({"drop_value": ["GFP"]})  # typo


def test_non_resolving_value_overlap_raises() -> None:
    with pytest.raises(ValueError, match="drop_values and record_values"):
        NonResolving.from_json(
            {"drop_values": ["X"], "record_values": ["X"]}
        )


def test_non_resolving_pattern_overlap_raises() -> None:
    with pytest.raises(ValueError, match="drop_patterns and record_patterns"):
        NonResolving.from_json(
            {"drop_patterns": ["contig"], "record_patterns": ["contig"]}
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
        "drop_values": ["GFP"],
        "record_values": ["SGK494"],
    }
    gm = GeneMapping.from_json(cfg)
    assert gm.non_resolving.classify("GFP") == "drop"
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


def test_dispatch_drop_values_orphans(
    central_gene_stub: CentralGeneTable,
) -> None:
    cfg = _base_mapping()
    cfg["non_resolving"] = {"drop_values": ["GFP"]}
    df = pd.DataFrame({"id": [1], "target_gene": ["GFP"]})
    gm = GeneMapping.from_json(cfg)
    link = gm.resolve_to_central_gene_table("t", df, Path("/dev/null"))
    assert link.central_gene_table_links == [(1, None)]
    # No stub created.
    assert len(central_gene_stub.entries) == 1  # just BRCA1


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
    # Stub is `manually_added=True`.
    assert central_gene_stub.entries[cg_id].manually_added is True
    assert central_gene_stub.entries[cg_id].human_symbol == "SGK494"


def test_dispatch_drop_patterns(
    central_gene_stub: CentralGeneTable,
) -> None:
    cfg = _base_mapping()
    cfg["non_resolving"] = {"drop_patterns": ["ensembl_human"]}
    df = pd.DataFrame({"id": [1, 2], "target_gene": ["ENSG00000123456", "BRCA1"]})
    gm = GeneMapping.from_json(cfg)
    link = gm.resolve_to_central_gene_table("t", df, Path("/dev/null"))
    # ENSG row is orphaned, BRCA1 row resolves.
    by_id = dict(link.central_gene_table_links)
    assert by_id[1] is None
    assert by_id[2] == 0
    assert len(central_gene_stub.entries) == 1  # no stub created for ENSG


def test_dispatch_fallback_warns_and_records(
    central_gene_stub: CentralGeneTable,
) -> None:
    # No non_resolving entry covers WEIRDGENE → fallback path: warn +
    # create stub + link. Test verifies the link/stub side; warning
    # output goes through the standard logger.
    cfg = _base_mapping()
    df = pd.DataFrame({"id": [1], "target_gene": ["WEIRDGENE"]})
    gm = GeneMapping.from_json(cfg)
    link = gm.resolve_to_central_gene_table("t", df, Path("/dev/null"))
    [(_, cg_id)] = link.central_gene_table_links
    assert cg_id is not None
    assert central_gene_stub.entries[cg_id].human_symbol == "WEIRDGENE"
    assert central_gene_stub.entries[cg_id].manually_added is True
