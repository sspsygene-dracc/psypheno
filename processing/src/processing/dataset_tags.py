"""Dataset tags: model system, anatomy (UBERON), stage, experiment type.

Tags describe the biological system a dataset's data come from. They are set at
dataset level in `data/datasets/<name>/config.yaml` (top-level keys) and may be
overridden per table (the same keys inside a `tables:` entry). Per key, a table
value replaces the dataset value; a key a table does not set is inherited.

    model_system: ineurons        # one of MODEL_SYSTEMS
    anatomy: [UBERON:0001950]     # UBERON CURIEs from data/ontology/uberon_terms.tsv
    stage: in_vitro               # optional, one of STAGES
    stage_detail: "NGN2 day 28"   # optional short free text
    experiment_type: crispri      # one of EXPERIMENT_TYPES
    anatomy_column: brodmann_area # optional, table level only

See docs/adding-datasets.md ("Dataset tags") for how to choose values.
"""

from __future__ import annotations

import csv
import functools
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Transition switch. While the existing dataset configs are being backfilled,
# a missing `model_system`, or missing `anatomy` on a non-curated dataset, is
# only logged as a warning. Flip to True once every config.yaml carries tags;
# from then on both are hard errors. Unknown values and unknown CURIEs are
# errors regardless of this switch.
REQUIRE_DATASET_TAGS = True

MODEL_SYSTEMS: tuple[str, ...] = (
    "in_vivo",
    "postmortem",
    "organoid",
    "primary_culture",
    "ineurons",
    "ipsc_other",
    "cell_line",
    "curated",
)

STAGES: tuple[str, ...] = (
    "embryonic",
    "fetal",
    "postnatal",
    "adult",
    "larval",
    "in_vitro",
)

# What kind of experiment produced a table's data — for perturbation studies,
# how the genes were perturbed. One value per table: a table that mixes several
# perturbation kinds (e.g. CRISPRa and shRNA arms in one DEG table) is
# `multiple`. Order is the display order (e.g. /matrix "Group columns by").
EXPERIMENT_TYPES: tuple[str, ...] = (
    "crispr_ko",  # Cas9 knockout / loss-of-function edits, incl. mutant & crispant fish
    "crispri",  # CRISPR interference (dCas9-KRAB)
    "crispra",  # CRISPR activation
    "knockdown",  # RNAi (shRNA/siRNA) or antisense-oligo knockdown
    "overexpression",  # exogenous wild-type gene / tagged bait expression
    "isogenic_variant",  # engineered disease variant vs wild-type, same background
    "patient_lines",  # patient-derived cells / organoids vs control lines
    "drug_treatment",  # pharmacological treatment
    "multiple",  # one table combining several of the above
    "observational",  # no manipulation: postmortem case vs control, markers, ...
    "human_genetics",  # association statistics from human sequencing cohorts
    "curated",  # databases and curated gene lists
    "other",
)

# Model systems that do not need anatomy terms (non-experimental resources).
ANATOMY_OPTIONAL_MODEL_SYSTEMS: frozenset[str] = frozenset({"curated"})

# Keys accepted at both dataset and table level.
TAG_KEYS: tuple[str, ...] = (
    "model_system",
    "anatomy",
    "stage",
    "stage_detail",
    "experiment_type",
)
# Accepted at table level only.
TABLE_ONLY_TAG_KEYS: tuple[str, ...] = ("anatomy_column",)

# Coarse anatomical regions (/matrix "Group columns by: Region"). A table can
# carry several UBERON terms; it is assigned the FIRST region below that covers
# ALL of its terms, a term being covered when it is one of the region's anchor
# terms or lies under one (is_a/part_of closure). The cerebral lobes are listed
# with cerebral cortex because UBERON files a lobe under the cerebral hemisphere
# rather than the cortex, yet datasets tag lobes for cortical samples. Tables
# whose terms are not all in the brain go to `whole_organism` when they are
# tagged with the whole organism, otherwise to `other_tissue` (e.g. HEK293T →
# kidney); tables without anatomy (curated resources) get no region.
COARSE_REGIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "cerebral_cortex",
        (
            "UBERON:0000956",  # cerebral cortex
            "UBERON:0016525",  # frontal lobe
            "UBERON:0001871",  # temporal lobe
            "UBERON:0001872",  # parietal lobe
            "UBERON:0002021",  # occipital lobe
        ),
    ),
    ("forebrain", ("UBERON:0001890",)),  # other forebrain (telencephalon, ...)
    ("brain", ("UBERON:0000955",)),  # whole brain / unspecified brain region
)
WHOLE_ORGANISM = "UBERON:0000468"
COARSE_REGION_KEYS: tuple[str, ...] = (
    *(key for key, _ in COARSE_REGIONS),
    "whole_organism",
    "other_tissue",
)

_DEFAULT_UBERON_TSV = (
    Path(__file__).resolve().parents[3] / "data" / "ontology" / "uberon_terms.tsv"
)


@dataclass(frozen=True)
class UberonTerm:
    id: str
    label: str
    ancestors: frozenset[str]


def uberon_terms_path() -> Path:
    """The vendored UBERON list; `SSPSYGENE_UBERON_TERMS` overrides (tests)."""
    override = os.environ.get("SSPSYGENE_UBERON_TERMS")
    return Path(override) if override else _DEFAULT_UBERON_TSV


@functools.lru_cache(maxsize=4)
def _load_uberon_terms(path: Path) -> dict[str, UberonTerm]:
    if not path.exists():
        raise FileNotFoundError(
            f"UBERON term list not found: {path} (built by "
            f"data/ontology/makeDoc.txt)"
        )
    terms: dict[str, UberonTerm] = {}
    with open(path, encoding="utf-8", newline="") as f:
        rows = (line for line in f if not line.startswith("#"))
        for row in csv.DictReader(rows, delimiter="\t"):
            ancestors = row.get("ancestors") or ""
            terms[row["id"]] = UberonTerm(
                id=row["id"],
                label=row["label"],
                ancestors=frozenset(a for a in ancestors.split(",") if a),
            )
    return terms


def uberon_terms() -> dict[str, UberonTerm]:
    return _load_uberon_terms(uberon_terms_path())


@dataclass(frozen=True)
class DatasetTags:
    """Effective (resolved) tags of one table."""

    model_system: str | None = None
    anatomy: tuple[str, ...] = ()
    stage: str | None = None
    stage_detail: str | None = None
    anatomy_column: str | None = None
    experiment_type: str | None = None

    def anatomy_terms(self) -> list[dict[str, str]]:
        """[{id, label}] in config order — the DB/API representation."""
        terms = uberon_terms()
        return [{"id": t, "label": terms[t].label} for t in self.anatomy]

    def anatomy_closure(self) -> list[str]:
        """Every tagged term plus all its is_a/part_of ancestors, sorted.

        A region filter on term R matches this table iff R is in the closure,
        i.e. the table is tagged R or any subregion / subtype of R.
        """
        terms = uberon_terms()
        out: set[str] = set(self.anatomy)
        for t in self.anatomy:
            out |= terms[t].ancestors
        return sorted(out)

    def coarse_region(self) -> str | None:
        """One of COARSE_REGION_KEYS (rule at COARSE_REGIONS), or None."""
        if not self.anatomy:
            return None
        terms = uberon_terms()

        def covered(term: str, anchors: tuple[str, ...]) -> bool:
            return term in anchors or not terms[term].ancestors.isdisjoint(anchors)

        for key, anchors in COARSE_REGIONS:
            if all(covered(t, anchors) for t in self.anatomy):
                return key
        if WHOLE_ORGANISM in self.anatomy:
            return "whole_organism"
        return "other_tissue"


def validate_tag_values(raw: dict[str, Any], *, context: str) -> dict[str, Any]:
    """Check the tag keys present in `raw`; return them normalized.

    Only keys actually present are returned, so the result can be layered
    (dataset values, then table overrides). Raises ValueError on any malformed
    or unknown value — these are always errors, independent of
    REQUIRE_DATASET_TAGS.
    """
    out: dict[str, Any] = {}
    if "model_system" in raw:
        ms = raw["model_system"]
        if not isinstance(ms, str) or ms not in MODEL_SYSTEMS:
            raise ValueError(
                f"{context}: model_system {ms!r} is not one of "
                f"{', '.join(MODEL_SYSTEMS)}."
            )
        out["model_system"] = ms
    if "anatomy" in raw:
        anatomy = raw["anatomy"]
        if isinstance(anatomy, str):
            anatomy = [anatomy]
        if not isinstance(anatomy, list) or not all(
            isinstance(a, str) for a in anatomy
        ):
            raise ValueError(
                f"{context}: anatomy must be a list of UBERON CURIEs "
                f"(e.g. [UBERON:0000955]); got {raw['anatomy']!r}."
            )
        cleaned = [a.strip() for a in anatomy]
        terms = uberon_terms()
        unknown = [a for a in cleaned if a not in terms]
        if unknown:
            raise ValueError(
                f"{context}: anatomy term(s) {unknown} are not in the vendored "
                f"UBERON list ({uberon_terms_path().name}). Use an "
                f"UBERON:NNNNNNN id that exists — check "
                f"https://www.ebi.ac.uk/ols4/ontologies/uberon. A real term "
                f"missing from the list needs adding via "
                f"data/ontology/build_uberon_terms.py."
            )
        dupes = sorted({a for a in cleaned if cleaned.count(a) > 1})
        if dupes:
            raise ValueError(f"{context}: anatomy lists {dupes} more than once.")
        out["anatomy"] = tuple(cleaned)
    if "stage" in raw:
        stage = raw["stage"]
        if not isinstance(stage, str) or stage not in STAGES:
            raise ValueError(
                f"{context}: stage {stage!r} is not one of {', '.join(STAGES)}."
            )
        out["stage"] = stage
    if "stage_detail" in raw:
        detail = raw["stage_detail"]
        if not isinstance(detail, str) or not detail.strip():
            raise ValueError(
                f"{context}: stage_detail must be a short non-empty string; "
                f"got {detail!r}."
            )
        out["stage_detail"] = detail.strip()
    if "experiment_type" in raw:
        et = raw["experiment_type"]
        if not isinstance(et, str) or et not in EXPERIMENT_TYPES:
            raise ValueError(
                f"{context}: experiment_type {et!r} is not one of "
                f"{', '.join(EXPERIMENT_TYPES)}."
            )
        out["experiment_type"] = et
    return out


def resolve_table_tags(
    dataset_tags: dict[str, Any],
    table_raw: dict[str, Any],
    *,
    context: str,
    normalize_column: Any = None,
) -> DatasetTags:
    """Layer a table's tag overrides over its dataset's (already validated) tags.

    Also applies the completeness rule: a missing model_system or
    experiment_type, or no anatomy on a non-curated table, is a warning while REQUIRE_DATASET_TAGS is False and an
    error once it is True.
    """
    merged = dict(dataset_tags)
    merged.update(validate_tag_values(table_raw, context=context))

    anatomy_column = table_raw.get("anatomy_column")
    if anatomy_column is not None:
        if not isinstance(anatomy_column, str) or not anatomy_column.strip():
            raise ValueError(
                f"{context}: anatomy_column must be a column name; got "
                f"{anatomy_column!r}."
            )
        anatomy_column = (
            normalize_column(anatomy_column) if normalize_column else anatomy_column
        )

    tags = DatasetTags(
        model_system=merged.get("model_system"),
        anatomy=merged.get("anatomy", ()),
        stage=merged.get("stage"),
        stage_detail=merged.get("stage_detail"),
        anatomy_column=anatomy_column,
        experiment_type=merged.get("experiment_type"),
    )

    problems: list[str] = []
    if tags.model_system is None:
        problems.append(
            f"no model_system (one of {', '.join(MODEL_SYSTEMS)})"
        )
    if (
        not tags.anatomy
        and tags.model_system not in ANATOMY_OPTIONAL_MODEL_SYSTEMS
    ):
        problems.append("no anatomy terms (required unless model_system is curated)")
    if tags.experiment_type is None:
        problems.append(
            f"no experiment_type (one of {', '.join(EXPERIMENT_TYPES)})"
        )
    if anatomy_column is not None and not tags.anatomy:
        problems.append(
            "anatomy_column is set but anatomy is empty — list the union of "
            "the regions the column covers under `anatomy:`"
        )
    if problems:
        msg = f"{context}: dataset tags incomplete: {'; '.join(problems)}."
        if REQUIRE_DATASET_TAGS:
            raise ValueError(msg)
        logger.warning("%s", msg)
    return tags
