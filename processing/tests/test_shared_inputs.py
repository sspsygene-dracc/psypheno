"""Tests for shared/global-input handling (issue #205).

Network-free: covers the actionable error raised when a shared gene-reference
input is missing, and the config-driven discovery of which shared inputs
`sspsygene pull-data` should pull. The actual rsync/SSH transfer needs a live
server and isn't unit-tested here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from processing.shared_inputs import require_shared_input
from processing.pull_data import _shared_input_relpaths


def test_require_shared_input_passes_through_existing(tmp_path: Path) -> None:
    f = tmp_path / "hgnc.txt"
    f.write_text("present\n")
    assert require_shared_input(f) == f


def test_require_shared_input_message_points_at_pull_data(tmp_path: Path) -> None:
    missing = tmp_path / "homology" / "hgnc_complete_set.txt"
    with pytest.raises(FileNotFoundError) as exc:
        require_shared_input(missing, description="HGNC complete set")
    msg = str(exc.value)
    assert "HGNC complete set" in msg
    assert str(missing) in msg
    # The whole point of the ticket: tell the wrangler how to fix it.
    assert "sspsygene pull-data" in msg


def test_shared_input_relpaths_reads_gene_map_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "gene_map_files": {
                    "hgnc": "homology/hgnc_complete_set.txt",
                    "mgi": "homology/MGI_EntrezGene.rpt",
                    # duplicate value should be de-duped
                    "mgi_again": "homology/MGI_EntrezGene.rpt",
                    "empty": "",
                }
            }
        )
    )
    monkeypatch.setenv("SSPSYGENE_CONFIG_JSON", str(cfg))
    assert _shared_input_relpaths() == [
        "homology/hgnc_complete_set.txt",
        "homology/MGI_EntrezGene.rpt",
    ]


def test_shared_input_relpaths_missing_config_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SSPSYGENE_CONFIG_JSON", raising=False)
    assert _shared_input_relpaths() == []
