from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from processing.config import get_sspsygene_config
from processing.types.ensembl_gene import EnsemblGene
from processing.types.entrez_gene import EntrezGene
from processing.types.mgi_accession_id import MGIAcessionID


_ENSMUS_STR_TO_CHECK = "ENSMUSG00000071265"


_mgi_entrez_header = [
    "MGI Marker Accession ID",
    "Marker Symbol",
    "Status",
    "Marker Name",
    "cM Position",
    "Chromosome",
    "Type",
    "Secondary Accession IDs",
    "Entrez Gene ID",
    "Synonyms",
    "Feature Types",
    "Genome Coordinate Start",
    "Genome Coordinate End",
    "Strand",
    "BioTypes",
]


_mgi_elem_types = {
    "Complex/Cluster/Region",
    "BAC/YAC end",
    "Cytogenetic Marker",
    "QTL",
    "Transgene",
    "Pseudogene",
    "DNA Segment",
    "Gene",
    "Other Genome Feature",
}


@dataclass
class CentralGeneTableEntry:

    row_id: int
    human_symbol: str | None
    human_entrez_gene: EntrezGene | None
    human_ensembl_gene: EnsemblGene | None
    hgnc_id: str | None
    mouse_symbols: set[str]
    mouse_mgi_accession_ids: set[MGIAcessionID]
    mouse_ensembl_genes: set[EnsemblGene]
    human_synonyms: set[str]
    mouse_synonyms: set[str]
    manually_added: bool = False
    dataset_names: set[str] = field(default_factory=set)
    used_human_names: set[str] = field(default_factory=set)
    used_mouse_names: set[str] = field(default_factory=set)
    used: bool = False

    def add_used_name(
        self, species: Literal["human", "mouse"], name: str, dataset_name: str
    ) -> None:
        self.used = True
        self.dataset_names.add(dataset_name)
        if species == "human":
            self.used_human_names.add(name)
        elif species == "mouse":
            self.used_mouse_names.add(name)
        else:
            raise ValueError(f"Invalid species: {species}")


@dataclass
class CentralGeneTable:

    entries: list[CentralGeneTableEntry] = field(default_factory=list)

    def get_mouse_map(
        self,
    ) -> dict[str, list[CentralGeneTableEntry]]:
        rv: dict[str, list[CentralGeneTableEntry]] = defaultdict(list)
        for entry in self.entries:
            for symbol in entry.mouse_symbols:
                rv[symbol].append(entry)
            for synonym in entry.mouse_synonyms:
                rv[synonym].append(entry)
            for ensg in entry.mouse_ensembl_genes:
                rv[ensg.ensembl_id].append(entry)
        return dict(rv)

    def get_human_map(
        self,
    ) -> dict[str, list[CentralGeneTableEntry]]:
        rv: dict[str, list[CentralGeneTableEntry]] = defaultdict(list)
        for entry in self.entries:
            if entry.human_symbol is not None:
                rv[entry.human_symbol].append(entry)
            for synonym in entry.human_synonyms:
                rv[synonym].append(entry)
            if entry.human_ensembl_gene is not None:
                rv[entry.human_ensembl_gene.ensembl_id].append(entry)
        return dict(rv)

    def get_species_map(
        self, species: Literal["human", "mouse"]
    ) -> dict[str, list[CentralGeneTableEntry]]:
        if species == "human":
            return self.get_human_map()
        elif species == "mouse":
            return self.get_mouse_map()
        else:
            raise ValueError(f"Invalid species: {species}")

    def add_manual_mouse_entry(
        self, symbol: str, dataset: str
    ) -> CentralGeneTableEntry:
        entry = CentralGeneTableEntry(
            row_id=len(self.entries),
            human_symbol=None,
            human_entrez_gene=None,
            human_ensembl_gene=None,
            hgnc_id=None,
            mouse_symbols={symbol},
            mouse_ensembl_genes=set(),
            mouse_mgi_accession_ids=set(),
            human_synonyms=set(),
            mouse_synonyms=set(),
            dataset_names={dataset},
            used_mouse_names={symbol},
            used=True,
            manually_added=True,
        )
        self.entries.append(entry)
        return entry

    def add_manual_human_entry(
        self, symbol: str, dataset: str
    ) -> CentralGeneTableEntry:
        entry = CentralGeneTableEntry(
            row_id=len(self.entries),
            human_symbol=symbol,
            human_entrez_gene=None,
            human_ensembl_gene=None,
            hgnc_id=None,
            mouse_symbols=set(),
            mouse_ensembl_genes=set(),
            mouse_mgi_accession_ids=set(),
            human_synonyms=set(),
            mouse_synonyms=set(),
            dataset_names={dataset},
            used_human_names={symbol},
            manually_added=True,
            used=True,
        )
        self.entries.append(entry)
        return entry

    def add_species_entry(
        self, species: Literal["human", "mouse"], symbol: str, dataset: str
    ) -> CentralGeneTableEntry:
        if species == "human":
            return self.add_manual_human_entry(symbol, dataset)
        elif species == "mouse":
            return self.add_manual_mouse_entry(symbol, dataset)
        else:
            raise ValueError(f"Invalid species: {species}")

    def get_hgnc_id_to_human_entrez_id(self) -> dict[str, EntrezGene]:
        rv_entrez: dict[str, EntrezGene] = {}
        for entry in self.entries:
            if entry.human_entrez_gene is None:
                continue
            if (
                entry.hgnc_id is None
            ):  # this is just to ensure we only get HGNC names --- manually added entries have no HGNC ID
                continue
            rv_entrez[entry.hgnc_id] = entry.human_entrez_gene
        return rv_entrez

    def construct(self):
        self.parse_hgnc(get_sspsygene_config().gene_map_config.hgnc_file)
        mgi_accession_id_to_hgnc, mgi_accession_id_to_ensembl = self.parse_mgi_homology(
            get_sspsygene_config().gene_map_config.alliance_homology_file
        )
        hgnc_to_human_entrez = self.get_hgnc_id_to_human_entrez_id()
        self.parse_mgi(
            get_sspsygene_config().gene_map_config.mgi_file,
            hgnc_to_human_entrez=hgnc_to_human_entrez,
            mgi_accession_id_to_hgnc=mgi_accession_id_to_hgnc,
            mgi_accession_id_to_ensembl=mgi_accession_id_to_ensembl,
        )

    def parse_hgnc(self, fname: Path) -> None:
        def get_entrez_id(row: dict[str, str]) -> int | None:
            entrez_id_str = row["entrez_id"]
            if entrez_id_str == "" or entrez_id_str == "null":
                return None
            return int(entrez_id_str)

        def get_ensembl_gene_id(row: dict[str, str]) -> EnsemblGene | None:
            ensembl_id_str = row["ensembl_gene_id"]
            if ensembl_id_str == "" or ensembl_id_str == "null":
                return None
            return EnsemblGene(ensembl_id_str)

        rows: list[dict[str, str]] = []
        with open(fname, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append(row)

        symbols: set[str] = {row["symbol"] for row in rows}
        for row in rows:
            synonyms = set(row["prev_symbol"].split("|")) - symbols
            entrez_id = get_entrez_id(row)
            ensembl_gene_id = get_ensembl_gene_id(row)
            symbol = row["symbol"]
            self.entries.append(
                CentralGeneTableEntry(
                    row_id=len(self.entries),
                    human_symbol=symbol,
                    human_entrez_gene=(
                        EntrezGene(entrez_id) if entrez_id is not None else None
                    ),
                    human_ensembl_gene=ensembl_gene_id,
                    hgnc_id=(
                        row["hgnc_id"]
                        if (row["hgnc_id"] and row["hgnc_id"] != "null")
                        else None
                    ),
                    mouse_symbols=set(),
                    mouse_ensembl_genes=set(),
                    mouse_mgi_accession_ids=set(),
                    human_synonyms=synonyms,
                    mouse_synonyms=set(),
                )
            )

    def parse_mgi_homology(
        self,
        alliance_homology_fname: Path,
    ) -> tuple[dict[MGIAcessionID, set[str]], dict[MGIAcessionID, set[EnsemblGene]]]:
        mgi_accession_id_to_hgnc: dict[MGIAcessionID, set[str]] = defaultdict(set)
        mgi_accession_id_to_ensembl: dict[MGIAcessionID, set[EnsemblGene]] = (
            defaultdict(set)
        )
        with open(alliance_homology_fname, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                mgi_accession_id = MGIAcessionID(row["MGI Accession ID"])
                hgnc_id = row["HGNC ID"]
                mgi_accession_id_to_hgnc[mgi_accession_id].add(hgnc_id)
                ensembl_id_str = row["Ensembl Gene ID"]
                if not (ensembl_id_str == "" or ensembl_id_str == "null"):
                    assert ensembl_id_str.startswith(
                        "ENSMUSG"
                    ), f"Invalid Ensembl ID: {ensembl_id_str} for MGI Accession ID {mgi_accession_id}"
                    ensembl_id = EnsemblGene(ensembl_id_str)
                    mgi_accession_id_to_ensembl[mgi_accession_id].add(ensembl_id)
        # all_values: set[EnsemblGene] = set()
        # entrez_of_interest: EntrezGene | None = None
        # for entrez_gene, values in ensembl_rv.items():
        #     all_values.update(values)
        #     if EnsemblGene(_ENSMUS_STR_TO_CHECK) in values:
        #         entrez_of_interest = entrez_gene
        # assert EnsemblGene(_ENSMUS_STR_TO_CHECK) in all_values
        # print(f"entrez_of_interest: {entrez_of_interest}")
        return mgi_accession_id_to_hgnc, mgi_accession_id_to_ensembl

    def parse_mgi(
        self,
        mgi_fname: Path,
        hgnc_to_human_entrez: dict[str, EntrezGene],
        mgi_accession_id_to_hgnc: dict[MGIAcessionID, set[str]],
        mgi_accession_id_to_ensembl: dict[MGIAcessionID, set[EnsemblGene]],
    ) -> None:
        rows: list[dict[str, str]] = []
        withdrawn_map: dict[str, set[str]] = defaultdict(set)

        with open(mgi_fname, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t", fieldnames=_mgi_entrez_header)
            for row in reader:
                status = row["Status"]
                assert status in {"O", "W"}
                if status == "W":
                    marker_name = row["Marker Name"]
                    if " = " in marker_name:
                        symbol = marker_name.split("=")[1].strip()
                        withdrawn_map[symbol].add(row["Marker Symbol"])
                    continue
                elem_type = row["Type"]
                assert elem_type in _mgi_elem_types
                rows.append(row)

        def get_mgi_accession_and_human_entrez_ids(
            row: dict[str, str],
        ) -> tuple[MGIAcessionID | None, set[EntrezGene] | None]:
            mgi_accession_id = MGIAcessionID(row["MGI Marker Accession ID"])
            hgnc_ids = mgi_accession_id_to_hgnc.get(mgi_accession_id, None)
            if hgnc_ids is None:
                return mgi_accession_id, None
            rv: set[EntrezGene] = {
                hgnc_to_human_entrez[hgnc_id]
                for hgnc_id in hgnc_ids
                if hgnc_id in hgnc_to_human_entrez
            }
            return mgi_accession_id, rv

        symbols: set[str] = {row["Marker Symbol"] for row in rows}
        all_synonyms: set[str] = set()

        human_entrez_to_central_entry: dict[EntrezGene, CentralGeneTableEntry] = {
            x.human_entrez_gene: x
            for x in self.entries
            if x.human_entrez_gene is not None
        }

        for row in rows:
            symbol = row["Marker Symbol"]
            synonyms = {x for x in row["Synonyms"].split("|") if x != ""} - symbols
            all_synonyms.update(synonyms)
            mgi_accession_id, human_entrez_ids = get_mgi_accession_and_human_entrez_ids(
                row
            )
            if human_entrez_ids:
                for human_entrez_id in human_entrez_ids:
                    central_entry = human_entrez_to_central_entry[human_entrez_id]
                    central_entry.mouse_symbols.add(symbol)
                    central_entry.mouse_synonyms.update(synonyms)
                    if mgi_accession_id:
                        central_entry.mouse_mgi_accession_ids.add(mgi_accession_id)
                        central_entry.mouse_ensembl_genes.update(
                            mgi_accession_id_to_ensembl.get(mgi_accession_id, set())
                        )
            else:
                entry = CentralGeneTableEntry(
                    row_id=len(self.entries),
                    human_symbol=None,
                    human_entrez_gene=None,
                    human_ensembl_gene=None,
                    hgnc_id=None,
                    mouse_symbols={symbol},
                    mouse_mgi_accession_ids=(
                        {mgi_accession_id} if mgi_accession_id else set()
                    ),
                    mouse_ensembl_genes=(
                        mgi_accession_id_to_ensembl.get(mgi_accession_id, set())
                        if mgi_accession_id
                        else set()
                    ),
                    human_synonyms=set(),
                    mouse_synonyms=synonyms,
                )
                self.entries.append(entry)

        mouse_symbol_to_central_entry: dict[str, list[CentralGeneTableEntry]] = (
            defaultdict(list)
        )
        for entry in self.entries:
            for symbol in entry.mouse_symbols:
                mouse_symbol_to_central_entry[symbol].append(entry)

        for symbol, other_ids in withdrawn_map.items():
            for other_id in other_ids:
                if other_id in symbols:
                    continue
                if other_id in all_synonyms:
                    continue
                if symbol not in mouse_symbol_to_central_entry:
                    continue
                for central_entry in mouse_symbol_to_central_entry[symbol]:
                    central_entry.mouse_synonyms.add(other_id)


CENTRAL_GENE_TABLE = CentralGeneTable()
CENTRAL_GENE_TABLE.construct()
