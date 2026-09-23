"""LLM-powered literature search for SSPsyGene genes.

For each gene listed in a YAML job file, we search for neuropsychiatric-relevant
papers and generate a brief summary with novelty classification.

Results are stored as individual JSON files in data/llm_gene_results/{SYMBOL}.json
and loaded into the llm_gene_results SQLite table during load-db.

Orchestration is handled by processing.run_llm_search (CLI:
`sspsygene run-llm-search`), which launches
parallel Claude CLI agents based on a YAML job config. Each agent researches
one gene and writes its result file directly.

This module provides:
  - build_*_prompt(): mode-specific prompt builders for agents
  - gene_results_dir() / load_gene_result(): per-gene file I/O helpers
"""

import json
from pathlib import Path
from typing import Any


# Valid operation modes
VALID_MODES = ("new", "verify", "update", "verify_update")


def gene_results_dir(data_dir: Path) -> Path:
    """Return the directory containing per-gene result files."""
    return data_dir / "llm_gene_results"


def load_gene_result(path: Path) -> dict[str, Any]:
    """Load a single per-gene result file."""
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Shared prompt fragments
# ---------------------------------------------------------------------------

_SEARCH_INSTRUCTIONS = """\
Search for published research about the gene {symbol} in neuropsychiatric \
and neurodevelopmental conditions (autism, schizophrenia, bipolar disorder, \
intellectual disability, psychiatric conditions, neurodevelopmental conditions).

Find the most relevant PubMed papers linking {symbol} to these conditions."""

_OUTPUT_FORMAT = """\
Write the result as a JSON file to {gene_file_path} with exactly these fields:
- "symbol": "{symbol}"
- "central_gene_id": {central_gene_id}
- "pubmed_links": Up to 3 most relevant papers as semicolon-separated \
markdown links: [Author et al. (Year) Brief title](https://pubmed.ncbi.nlm.nih.gov/PMID/)
- "summary": A 1-2 sentence summary of this gene's known role in \
neuropsychiatric/neurodevelopmental research. End with a novelty classification \
in parentheses: (well-established), (emerging evidence), or (novel candidate).
- "status": "results"
- "search_date": today's date in YYYY-MM-DD format
- "model": the model name you are running as

If no relevant papers exist for this gene in neuropsychiatric research, \
set pubmed_links and summary to null and status to "no_results".

Write only this one file. Your stdout only goes to a log file, so no \
summary or other output is needed."""

_EXISTING_DATA_BLOCK = """\
The gene currently has the following information on file:

PubMed links: {pubmed_links}

Summary: {summary}

Status: {status}"""


# ---------------------------------------------------------------------------
# Mode-specific prompt builders
# ---------------------------------------------------------------------------


def build_new_prompt(
    symbol: str,
    central_gene_id: int,
    gene_file_path: str,
) -> str:
    """Build a prompt for mode=new: full search from scratch."""
    return f"""\
{_SEARCH_INSTRUCTIONS.format(symbol=symbol)}

{_OUTPUT_FORMAT.format(
    symbol=symbol,
    central_gene_id=central_gene_id,
    gene_file_path=gene_file_path,
)}"""


def build_verify_prompt(
    symbol: str,
    central_gene_id: int,
    gene_file_path: str,
    existing_data: dict[str, Any],
) -> str:
    """Build a prompt for mode=verify: check and correct existing data."""
    return f"""\
Verify and correct the existing neuropsychiatric research information for \
the gene {symbol}.

{_EXISTING_DATA_BLOCK.format(
    pubmed_links=existing_data.get("pubmed_links") or "(none)",
    summary=existing_data.get("summary") or "(none)",
    status=existing_data.get("status", "unknown"),
)}

Your task:
1. Check each PubMed link — verify the PMID exists, the author/year/title \
are correct, and the paper is actually relevant to {symbol} and \
neuropsychiatric/neurodevelopmental conditions.
2. Check the summary — verify it accurately reflects the literature. Correct \
any factual errors. Verify the novelty classification is appropriate.
3. If any links are broken, incorrect, or irrelevant, replace them with \
correct ones (search for better papers if needed).
4. If the summary is inaccurate, rewrite it.

{_OUTPUT_FORMAT.format(
    symbol=symbol,
    central_gene_id=central_gene_id,
    gene_file_path=gene_file_path,
)}"""


def build_update_prompt(
    symbol: str,
    central_gene_id: int,
    gene_file_path: str,
    existing_data: dict[str, Any],
) -> str:
    """Build a prompt for mode=update: amend with new info, trust existing."""
    return f"""\
Update the existing neuropsychiatric research information for the gene \
{symbol} with any newer or additional findings.

{_EXISTING_DATA_BLOCK.format(
    pubmed_links=existing_data.get("pubmed_links") or "(none)",
    summary=existing_data.get("summary") or "(none)",
    status=existing_data.get("status", "unknown"),
)}

Take the existing information as correct and don't re-verify it — that is \
what verify mode is for. Spend this run on finding newer papers.

Your task:
1. Search for additional or more recent PubMed papers linking {symbol} to \
neuropsychiatric/neurodevelopmental conditions that are not already listed.
2. If you find better or more recent papers, include the best 3 total \
(you may keep some existing links and add new ones, or replace with better ones).
3. Update the summary to incorporate any new findings. Keep the novelty \
classification up to date.

{_OUTPUT_FORMAT.format(
    symbol=symbol,
    central_gene_id=central_gene_id,
    gene_file_path=gene_file_path,
)}"""


def build_verify_update_prompt(
    symbol: str,
    central_gene_id: int,
    gene_file_path: str,
    existing_data: dict[str, Any],
) -> str:
    """Build a prompt for mode=verify_update: verify then update."""
    return f"""\
Verify, correct, and update the neuropsychiatric research information for \
the gene {symbol}.

{_EXISTING_DATA_BLOCK.format(
    pubmed_links=existing_data.get("pubmed_links") or "(none)",
    summary=existing_data.get("summary") or "(none)",
    status=existing_data.get("status", "unknown"),
)}

Your task (two phases):

PHASE 1 — VERIFY:
1. Check each PubMed link — verify the PMID exists, the author/year/title \
are correct, and the paper is actually relevant to {symbol} and \
neuropsychiatric/neurodevelopmental conditions.
2. Check the summary for factual accuracy. Remove or correct any errors.

PHASE 2 — UPDATE:
3. Search for additional or more recent PubMed papers linking {symbol} to \
neuropsychiatric/neurodevelopmental conditions.
4. Include the best 3 total papers (keeping verified existing ones and \
adding new ones as appropriate).
5. Update the summary to incorporate new findings and correct any issues \
found during verification. Keep the novelty classification current.

{_OUTPUT_FORMAT.format(
    symbol=symbol,
    central_gene_id=central_gene_id,
    gene_file_path=gene_file_path,
)}"""
