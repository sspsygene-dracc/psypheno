from __future__ import annotations

from collections import defaultdict
import csv
import gzip
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from processing.config import get_sspsygene_config
from processing.reference_loci import (
    ReferenceLociIndex,
    build_reference_loci_index,
    stable_row_id,
)
from processing.shared_inputs import require_shared_input
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


EntryKind = Literal["gene", "control"]


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
    # `kind` distinguishes real-gene entries from perturbation controls
    # (NonTarget1, SafeTarget, GFP, Control_ST, etc.). Controls are
    # searchable but excluded from per-gene aggregates (volcano backgrounds,
    # combined-pvalue meta-analysis, the gene browser). See discussion #19.
    kind: EntryKind = "gene"
    dataset_names: set[str] = field(default_factory=set)
    used_human_names: set[str] = field(default_factory=set)
    used_mouse_names: set[str] = field(default_factory=set)
    used: bool = False
    # (table_name, species, matched_name) triples, one per way this gene was
    # reached (#225). The three sets above are flattened — they record *which*
    # tables used the gene and *which* names matched, but not the pairing. The
    # destination subsetter needs exactly that pairing: given the subset of
    # tables allowed on prod, it must recompute dataset_names / num_datasets
    # and re-intersect the synonym columns without re-running gene resolution.
    usages: set[tuple[str, str, str]] = field(default_factory=set)
    # Mouse-only entries whose MGI gene has several human orthologs and no
    # single best match (`CentralGeneTable.unresolved_orthologs`): the
    # candidates, as {"hgnc_id", "symbol", "central_gene_id"} dicts sorted by
    # symbol. Empty for every other entry.
    candidate_human_orthologs: list[dict[str, str | int]] = field(
        default_factory=list
    )

    def add_used_name(
        self, species: Literal["human", "mouse"], name: str, dataset_name: str
    ) -> None:
        """Record that *name* (a `species` identifier) matched this gene in
        `dataset_name`.

        `dataset_name` is really the primary *table* name, not the dataset
        directory — that predates #225 and is why central_gene.dataset_names
        holds table names. The DB-level dataset↔table mapping lives in
        `data_tables.dataset` / `dataset_destinations`.
        """
        if species not in ("human", "mouse"):
            raise ValueError(f"Invalid species: {species}")
        self.used = True
        self.dataset_names.add(dataset_name)
        if species == "human":
            self.used_human_names.add(name)
        else:
            self.used_mouse_names.add(name)
        self.usages.add((dataset_name, species, name))


@dataclass
class CentralGeneTable:

    entries: list[CentralGeneTableEntry] = field(default_factory=list)
    _cached_human_map: dict[str, list[CentralGeneTableEntry]] | None = field(
        default=None, repr=False
    )
    _cached_mouse_map: dict[str, list[CentralGeneTableEntry]] | None = field(
        default=None, repr=False
    )
    # Loci that exist in GENCODE / NCBI but not HGNC, looked up lazily: there
    # are ~250k of them and a build uses a few thousand, so materializing all
    # of them as entries would be wasted work (only `used` entries are written).
    reference_loci: ReferenceLociIndex = field(
        default_factory=ReferenceLociIndex, repr=False
    )
    _assigned_row_ids: set[int] = field(default_factory=set, repr=False)

    def _stable_row_id(self, key: str) -> int:
        """A hash-derived row_id for `key`, unique within this build.

        Positional IDs (`len(self.entries)`) shift whenever anything earlier in
        the build changes — adding one dataset-only stub renumbered ~103k of
        them in a single day, silently repointing every stored central_gene_id
        in the meta / overview DBs at a different gene. Hashing the gene's own
        stable key removes that coupling.

        Collisions are astronomically rare (~1e-4 per build at this scale)
        but not impossible, so probe rather than assume.
        """
        row_id = stable_row_id(key)
        while row_id in self._assigned_row_ids:
            row_id = stable_row_id(f"{key}#{row_id}")
        self._assigned_row_ids.add(row_id)
        return row_id

    def get_mouse_map(
        self,
    ) -> dict[str, list[CentralGeneTableEntry]]:
        if self._cached_mouse_map is not None:
            return self._cached_mouse_map
        rv: dict[str, list[CentralGeneTableEntry]] = defaultdict(list)
        for entry in self.entries:
            for symbol in entry.mouse_symbols:
                rv[symbol].append(entry)
            for synonym in entry.mouse_synonyms:
                rv[synonym].append(entry)
            for ensg in entry.mouse_ensembl_genes:
                rv[ensg.ensembl_id].append(entry)
        self._cached_mouse_map = dict(rv)
        return self._cached_mouse_map

    def get_human_map(
        self,
    ) -> dict[str, list[CentralGeneTableEntry]]:
        if self._cached_human_map is not None:
            return self._cached_human_map
        rv: dict[str, list[CentralGeneTableEntry]] = defaultdict(list)
        for entry in self.entries:
            if entry.human_symbol is not None:
                rv[entry.human_symbol].append(entry)
            for synonym in entry.human_synonyms:
                rv[synonym].append(entry)
            if entry.human_ensembl_gene is not None:
                rv[entry.human_ensembl_gene.ensembl_id].append(entry)
        self._cached_human_map = dict(rv)
        return self._cached_human_map

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
        self, symbol: str, dataset: str, *, kind: EntryKind = "gene"
    ) -> CentralGeneTableEntry:
        entry = CentralGeneTableEntry(
            row_id=self._stable_row_id(f"stub:mouse:{symbol}"),
            human_symbol=None,
            human_entrez_gene=None,
            human_ensembl_gene=None,
            hgnc_id=None,
            mouse_symbols={symbol},
            mouse_ensembl_genes=set(),
            mouse_mgi_accession_ids=set(),
            human_synonyms=set(),
            mouse_synonyms=set(),
            manually_added=True,
            kind=kind,
        )
        # Route through add_used_name rather than seeding dataset_names /
        # used_mouse_names / used inline, so this stub path also records a
        # central_gene_usage triple (#225). Stub entries are always freshly
        # allocated, so their sole usage is this one — which is what makes them
        # drop cleanly when their table isn't a subset member.
        entry.add_used_name(species="mouse", name=symbol, dataset_name=dataset)
        self.entries.append(entry)
        return entry

    def add_manual_human_entry(
        self, symbol: str, dataset: str, *, kind: EntryKind = "gene"
    ) -> CentralGeneTableEntry:
        entry = CentralGeneTableEntry(
            row_id=self._stable_row_id(f"stub:human:{symbol}"),
            human_symbol=symbol,
            human_entrez_gene=None,
            human_ensembl_gene=None,
            hgnc_id=None,
            mouse_symbols=set(),
            mouse_ensembl_genes=set(),
            mouse_mgi_accession_ids=set(),
            human_synonyms=set(),
            mouse_synonyms=set(),
            manually_added=True,
            kind=kind,
        )
        # See add_manual_mouse_entry: single recording point for usages (#225).
        entry.add_used_name(species="human", name=symbol, dataset_name=dataset)
        self.entries.append(entry)
        return entry

    def add_species_entry(
        self,
        species: Literal["human", "mouse"],
        symbol: str,
        dataset: str,
        *,
        kind: EntryKind = "gene",
    ) -> CentralGeneTableEntry:
        if species == "human":
            return self.add_manual_human_entry(symbol, dataset, kind=kind)
        elif species == "mouse":
            return self.add_manual_mouse_entry(symbol, dataset, kind=kind)
        else:
            raise ValueError(f"Invalid species: {species}")

    def add_reference_entry(
        self, name: str, dataset: str
    ) -> CentralGeneTableEntry | None:
        """Materialize the GENCODE / NCBI locus `name` refers to, if any.

        Returns None when no locus claims the name, which leaves the caller on
        its existing stub path. Unlike a stub, the entry carries the locus's
        stable identifiers, is shared by every dataset naming it under *any* of
        its names, and is not `manually_added`.
        """
        locus = self.reference_loci.get(name)
        if locus is None:
            return None
        entry = CentralGeneTableEntry(
            row_id=self._stable_row_id(locus.key),
            human_symbol=locus.display,
            human_entrez_gene=(
                EntrezGene(locus.entrez_id) if locus.entrez_id is not None else None
            ),
            human_ensembl_gene=(
                EnsemblGene(locus.ensembl_id) if locus.ensembl_id else None
            ),
            hgnc_id=None,
            mouse_symbols=set(),
            mouse_ensembl_genes=set(),
            mouse_mgi_accession_ids=set(),
            # The locus's other names (an NCBI symbol for the same locus)
            # become synonyms, so a second dataset naming it differently
            # reaches the same entry — that is the cross-dataset identity a
            # stub never had. The ENSG is excluded: get_human_map already keys
            # on human_ensembl_gene, and listing it twice would link a row to
            # this entry twice.
            human_synonyms={
                n
                for n in locus.names
                if n not in (locus.display, locus.ensembl_id)
            },
            mouse_synonyms=set(),
            manually_added=False,
        )
        entry.add_used_name(species="human", name=name, dataset_name=dataset)
        self.entries.append(entry)
        # Register every name of the locus so later values reach this entry
        # without going through add_reference_entry again.
        if self._cached_human_map is not None:
            for locus_name in locus.names | {locus.display}:
                bucket = self._cached_human_map.setdefault(locus_name, [])
                if entry not in bucket:
                    bucket.append(entry)
        return entry

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
        gene_map = get_sspsygene_config().gene_map_config
        self.parse_hgnc(
            require_shared_input(gene_map.hgnc_file, description="HGNC complete set")
        )
        mgi_accession_id_to_hgnc, mgi_accession_id_to_ensembl = self.parse_mgi_homology(
            require_shared_input(
                gene_map.alliance_homology_file, description="Alliance homology"
            )
        )
        best_orthologs = (
            parse_alliance_best_orthologs(gene_map.alliance_orthology_file)
            if gene_map.alliance_orthology_file is not None
            and gene_map.alliance_orthology_file.exists()
            else {}
        )
        if not best_orthologs:
            logging.getLogger(__name__).warning(
                "Alliance orthology file missing; mouse genes with several human "
                "orthologs resolve only by a same-symbol match"
            )
        mgi_accession_id_to_hgnc = self.resolve_multi_orthologs(
            mgi_accession_id_to_hgnc, best_orthologs
        )
        hgnc_to_human_entrez = self.get_hgnc_id_to_human_entrez_id()
        self.parse_mgi(
            require_shared_input(gene_map.mgi_file, description="MGI EntrezGene"),
            hgnc_to_human_entrez=hgnc_to_human_entrez,
            mgi_accession_id_to_hgnc=mgi_accession_id_to_hgnc,
            mgi_accession_id_to_ensembl=mgi_accession_id_to_ensembl,
        )
        self.attach_candidate_orthologs()
        self.build_reference_loci(gene_map)

    def attach_candidate_orthologs(self) -> None:
        """Copy `unresolved_orthologs` onto the mouse-only entries they belong
        to, resolving each HGNC id to its human entry (symbol + row id) so the
        web app can name and link the candidates. HGNC ids with no human entry
        (withdrawn since the homology report was written) are dropped."""
        unresolved = getattr(self, "unresolved_orthologs", {})
        if not unresolved:
            return
        human_by_hgnc = {
            e.hgnc_id: e for e in self.entries if e.hgnc_id and e.human_symbol
        }
        for entry in self.entries:
            if entry.human_symbol is not None or not entry.mouse_mgi_accession_ids:
                continue
            hgnc_ids: set[str] = set()
            for mgi in entry.mouse_mgi_accession_ids:
                hgnc_ids |= unresolved.get(mgi, set())
            candidates = [human_by_hgnc[h] for h in hgnc_ids if h in human_by_hgnc]
            entry.candidate_human_orthologs = [
                {
                    "hgnc_id": str(h.hgnc_id),
                    "symbol": str(h.human_symbol),
                    "central_gene_id": h.row_id,
                }
                for h in sorted(candidates, key=lambda h: str(h.human_symbol))
            ]

    def build_reference_loci(self, gene_map) -> None:
        """Index the GENCODE / NCBI loci HGNC doesn't name.

        Runs after HGNC and MGI so `claimed_names` is the full set of names the
        existing entries already answer to — a reference locus never shadows a
        real symbol or synonym.
        """
        claimed_names = set(self.get_human_map()) | set(self.get_mouse_map())
        self.reference_loci = build_reference_loci_index(
            gencode_paths=list(gene_map.gencode_gtf_files),
            ncbi_gene_info_path=gene_map.ncbi_gene_info_file,
            hgnc_ensembl_ids={
                entry.human_ensembl_gene.ensembl_id
                for entry in self.entries
                if entry.human_ensembl_gene is not None
            },
            hgnc_ids={
                entry.hgnc_id for entry in self.entries if entry.hgnc_id is not None
            },
            hgnc_entrez_ids={
                entry.human_entrez_gene.entrez_id
                for entry in self.entries
                if entry.human_entrez_gene is not None
            },
            claimed_names=claimed_names,
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
            self._assigned_row_ids.add(self.entries[-1].row_id)

    def resolve_multi_orthologs(
        self,
        mgi_accession_id_to_hgnc: dict[MGIAcessionID, set[str]],
        best_orthologs: dict[str, set[str]],
    ) -> dict[MGIAcessionID, set[str]]:
        """Reduce each mouse gene's human orthologs to at most one.

        Linking a mouse gene to every listed ortholog would turn one mouse
        result into several pieces of human evidence (pseudogenes, paralogs:
        Pmch -> PMCH, PMCHL1, PMCHL2). So:

        1. the Alliance best-and-best-reverse ortholog, when there is exactly
           one among the candidates;
        2. otherwise (none, or a tie) the candidate whose symbol is the mouse
           symbol in upper case (Nomo1 -> NOMO1 out of NOMO1 / NOMO2);
        3. otherwise none: the mouse gene keeps its own row.

        `self.unresolved_orthologs` records the candidates of case 3.
        """
        log = logging.getLogger(__name__)
        symbol_by_hgnc = {
            e.hgnc_id: e.human_symbol for e in self.entries if e.hgnc_id and e.human_symbol
        }
        self.unresolved_orthologs: dict[MGIAcessionID, set[str]] = {}
        resolved: dict[MGIAcessionID, set[str]] = {}
        counts = {"best": 0, "symbol": 0, "unresolved": 0}
        for mgi, hgnc_ids in mgi_accession_id_to_hgnc.items():
            if len(hgnc_ids) <= 1:
                resolved[mgi] = hgnc_ids
                continue
            best = hgnc_ids & best_orthologs.get(str(mgi), set())
            if len(best) == 1:
                resolved[mgi] = best
                counts["best"] += 1
                continue
            mouse_symbol = self._mouse_symbol_by_mgi.get(mgi, "")
            pool = best or hgnc_ids
            same = {h for h in pool if symbol_by_hgnc.get(h, "").upper() == mouse_symbol.upper()}
            if mouse_symbol and len(same) == 1:
                resolved[mgi] = same
                counts["symbol"] += 1
                continue
            self.unresolved_orthologs[mgi] = hgnc_ids
            resolved[mgi] = set()
            counts["unresolved"] += 1
        log.info(
            "Mouse genes with several human orthologs: %d by Alliance best match, "
            "%d by same symbol, %d left mouse-only",
            counts["best"],
            counts["symbol"],
            counts["unresolved"],
        )
        return resolved

    def parse_mgi_homology(
        self,
        alliance_homology_fname: Path,
    ) -> tuple[dict[MGIAcessionID, set[str]], dict[MGIAcessionID, set[EnsemblGene]]]:
        mgi_accession_id_to_hgnc: dict[MGIAcessionID, set[str]] = defaultdict(set)
        self._mouse_symbol_by_mgi: dict[MGIAcessionID, str] = {}
        mgi_accession_id_to_ensembl: dict[MGIAcessionID, set[EnsemblGene]] = (
            defaultdict(set)
        )
        with open(alliance_homology_fname, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                mgi_accession_id = MGIAcessionID(row["MGI Accession ID"])
                self._mouse_symbol_by_mgi[mgi_accession_id] = row["Marker Symbol"]
                # One row per mouse gene; several human orthologs come
                # pipe-separated in one field ("HGNC:9110|HGNC:9111|HGNC:9109").
                for hgnc_id in row["HGNC ID"].split("|"):
                    hgnc_id = hgnc_id.strip()
                    if hgnc_id and hgnc_id != "null":
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
                self._assigned_row_ids.add(entry.row_id)

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


_CENTRAL_GENE_TABLE: CentralGeneTable | None = None


def get_central_gene_table() -> CentralGeneTable:
    global _CENTRAL_GENE_TABLE
    if _CENTRAL_GENE_TABLE is None:
        _CENTRAL_GENE_TABLE = CentralGeneTable()
        _CENTRAL_GENE_TABLE.construct()
    return _CENTRAL_GENE_TABLE


def parse_alliance_best_orthologs(path: Path) -> dict[str, set[str]]:
    """MGI id -> HGNC ids that are its Alliance best *and* best-reverse
    human ortholog. Reads the mouse–human subset of the Alliance combined
    orthology file (gzip or plain TSV, `#` comment lines allowed)."""
    opener = gzip.open if path.suffix == ".gz" else open
    best: dict[str, set[str]] = defaultdict(set)
    with opener(path, "rt", encoding="utf-8") as f:
        rows = csv.DictReader((line for line in f if not line.startswith("#")), delimiter="\t")
        for row in rows:
            if row.get("IsBestScore") != "Yes" or row.get("IsBestRevScore") != "Yes":
                continue
            g1, g2 = row["Gene1ID"], row["Gene2ID"]
            if g1.startswith("MGI:") and g2.startswith("HGNC:"):
                best[g1].add(g2)
            elif g1.startswith("HGNC:") and g2.startswith("MGI:"):
                best[g2].add(g1)
    return best
