"""LLM-powered literature search for top-ranked SSPsyGene genes.

For each of the top genes (union of top-N from each of 4 combined p-value
ranking methods), we search for neuropsychiatric-relevant papers and generate
a brief summary with novelty classification.

Results are stored as individual JSON files in data/llm_gene_results/{SYMBOL}.json
and loaded into the llm_gene_results SQLite table during load-db.

Orchestration is handled by processing.run_llm_search (CLI:
`sspsygene run-llm-search`), which launches
parallel Claude CLI agents based on a YAML job config. Each agent researches
one gene and writes its result file directly.

This module provides:
  - _get_top_genes(): identify which genes to search
  - build_*_prompt(): mode-specific prompt builders for agents
  - gene_results_dir() / load_gene_result(): per-gene file I/O helpers
"""

import json
import sqlite3
from pathlib import Path
from typing import Any


# Default flag filters matching the web UI defaults
_DEFAULT_HIDE_FLAGS = [
    "heat_shock",
    "mitochondrial_rna",
    "no_hgnc",
    "non_coding",
    "pseudogene",
    "ribosomal",
    "ubiquitin",
]

# Valid operation modes
VALID_MODES = ("new", "verify", "update", "verify_update")


def gene_results_dir(data_dir: Path) -> Path:
    """Return the directory containing per-gene result files."""
    return data_dir / "llm_gene_results"


def load_gene_result(path: Path) -> dict[str, Any]:
    """Load a single per-gene result file."""
    with open(path) as f:
        return json.load(f)


def get_top_genes(db_path: Path, top_n: int) -> list[dict[str, Any]]:
    """Query DB for top genes across all 4 ranking methods.

    Returns list of {central_gene_id, human_symbol} dicts.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Build WHERE clause to exclude flagged genes
    flag_conditions = " OR ".join(
        f"cp.gene_flags LIKE '%{flag}%'" for flag in _DEFAULT_HIDE_FLAGS
    )
    flag_where = f"WHERE (cp.gene_flags IS NULL OR NOT ({flag_conditions}))"

    # Get union of top-N from each method
    methods = ["fisher_pvalue", "stouffer_pvalue", "cauchy_pvalue", "hmp_pvalue"]
    all_gene_ids: set[int] = set()
    for method in methods:
        rows = conn.execute(
            f"SELECT cp.central_gene_id "
            f"FROM gene_combined_pvalues cp "
            f"JOIN central_gene cg ON cg.id = cp.central_gene_id "
            f"{flag_where} "
            f"ORDER BY cp.{method} ASC NULLS LAST "
            f"LIMIT ?",
            (top_n,),
        ).fetchall()
        for row in rows:
            all_gene_ids.add(row["central_gene_id"])

    # Get symbols for all selected genes
    genes = []
    for gene_id in sorted(all_gene_ids):
        row = conn.execute(
            "SELECT id, human_symbol FROM central_gene WHERE id = ?",
            (gene_id,),
        ).fetchone()
        if row and row["human_symbol"]:
            genes.append(
                {"central_gene_id": row["id"], "human_symbol": row["human_symbol"]}
            )

    conn.close()
    return genes


# ---------------------------------------------------------------------------
# Shared prompt fragments
# ---------------------------------------------------------------------------

_SEARCH_INSTRUCTIONS = """\
Search for published research about the gene {symbol} in neuropsychiatric \
and neurodevelopmental disorders (autism, schizophrenia, bipolar disorder, \
intellectual disability, psychiatric disorders, neurodevelopmental conditions).

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

Write ONLY the JSON file. No other output or files."""

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
neuropsychiatric/neurodevelopmental disorders.
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

Take the existing information at face value — do NOT re-verify it.

Your task:
1. Search for additional or more recent PubMed papers linking {symbol} to \
neuropsychiatric/neurodevelopmental disorders that are not already listed.
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
neuropsychiatric/neurodevelopmental disorders.
2. Check the summary for factual accuracy. Remove or correct any errors.

PHASE 2 — UPDATE:
3. Search for additional or more recent PubMed papers linking {symbol} to \
neuropsychiatric/neurodevelopmental disorders.
4. Include the best 3 total papers (keeping verified existing ones and \
adding new ones as appropriate).
5. Update the summary to incorporate new findings and correct any issues \
found during verification. Keep the novelty classification current.

{_OUTPUT_FORMAT.format(
    symbol=symbol,
    central_gene_id=central_gene_id,
    gene_file_path=gene_file_path,
)}"""
