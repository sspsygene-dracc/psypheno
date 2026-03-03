#!/usr/bin/env python3
"""Parallel LLM gene search orchestrator.

Reads a YAML job file and launches parallel Claude CLI agents, each
researching one gene for neuropsychiatric associations. Each agent writes
its result directly to data/llm_gene_results/{SYMBOL}.json.

Usage:
    python run_llm_search.py llm_jobs.yaml
    python run_llm_search.py llm_jobs.yaml --dry-run
    python run_llm_search.py llm_jobs.yaml --model opus
    python run_llm_search.py llm_jobs.yaml --max-workers 10

    # Auto-generate a job config from the database:
    python run_llm_search.py --generate-config --top-n 100 --output llm_jobs.yaml
"""

import argparse
import concurrent.futures
import functools
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

# Force unbuffered stdout so log lines appear immediately
print = functools.partial(print, flush=True)  # type: ignore[assignment]

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
GENE_RESULTS_DIR = DATA_DIR / "llm_gene_results"
LOGS_DIR = SCRIPT_DIR / "logs"
SETTINGS_FILE = SCRIPT_DIR / ".claude" / "settings.json"

# Defaults
DEFAULT_MAX_WORKERS = 20
DEFAULT_TIMEOUT = 1800  # 30 minutes per gene
DEFAULT_MAX_BUDGET = "2.00"
DEFAULT_MODEL = "sonnet"
VALID_MODELS = ("sonnet", "opus")

# Add src to path so we can import llm_search
sys.path.insert(0, str(SCRIPT_DIR / "src"))
from processing.llm_search import (
    VALID_MODES,
    _get_top_genes,
    build_new_prompt,
    build_update_prompt,
    build_verify_prompt,
    build_verify_update_prompt,
    load_gene_result,
)


def load_jobs(yaml_path: str) -> list[dict]:
    """Load and validate pipeline jobs from a YAML file."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    jobs = data.get("jobs", [])
    if not jobs:
        raise ValueError(f"No jobs found in {yaml_path}")

    for i, job in enumerate(jobs):
        if "symbol" not in job:
            raise ValueError(f"Job {i} missing 'symbol': {job}")
        if "mode" not in job:
            raise ValueError(
                f"Job for '{job['symbol']}' missing 'mode' "
                f"({', '.join(VALID_MODES)})"
            )
        mode = str(job["mode"]).lower()
        if mode not in VALID_MODES:
            raise ValueError(
                f"Job for '{job['symbol']}' has invalid mode '{mode}' "
                f"(must be: {', '.join(VALID_MODES)})"
            )

    return jobs


def resolve_central_gene_id(symbol: str) -> int | None:
    """Look up central_gene_id from an existing result file, if any."""
    path = GENE_RESULTS_DIR / f"{symbol}.json"
    if path.exists():
        data = load_gene_result(path)
        return data.get("central_gene_id")
    return None


def build_prompt_for_job(job: dict) -> tuple[str, str | None]:
    """Build the agent prompt for a job. Returns (prompt, skip_reason)."""
    symbol = job["symbol"]
    mode = str(job["mode"]).lower()
    gene_file = GENE_RESULTS_DIR / f"{symbol}.json"
    gene_file_path = str(gene_file)

    # For 'new' mode, skip if file already exists
    if mode == "new":
        if gene_file.exists():
            return "", f"file already exists (mode=new skips existing)"
        central_gene_id = job.get("central_gene_id", 0)
        return build_new_prompt(symbol, central_gene_id, gene_file_path), None

    # For verify/update/verify_update, file must exist
    if not gene_file.exists():
        return "", f"no existing file (mode={mode} requires one)"

    existing_data = load_gene_result(gene_file)
    central_gene_id = existing_data.get("central_gene_id", 0)

    if mode == "verify":
        return (
            build_verify_prompt(symbol, central_gene_id, gene_file_path, existing_data),
            None,
        )
    elif mode == "update":
        return (
            build_update_prompt(symbol, central_gene_id, gene_file_path, existing_data),
            None,
        )
    elif mode == "verify_update":
        return (
            build_verify_update_prompt(
                symbol, central_gene_id, gene_file_path, existing_data
            ),
            None,
        )

    return "", f"unknown mode '{mode}'"


def run_agent(
    symbol: str,
    prompt: str,
    model: str,
    max_budget: str,
    timeout: int,
    semaphore: threading.Semaphore,
) -> dict:
    """Run a single gene search agent via Claude CLI."""
    start_time = time.time()
    log_file = LOGS_DIR / f"{symbol}.log"

    with semaphore:
        try:
            result = subprocess.run(
                [
                    "claude",
                    "-p",
                    "--model", model,
                    "--max-budget-usd", max_budget,
                    "--settings", str(SETTINGS_FILE),
                    prompt,
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout,
                env={
                    **{k: v for k, v in os.environ.items() if k != "CLAUDECODE"},
                    "CLAUDE_CODE_ENTRYPOINT": "cli",
                },
            )

            elapsed = time.time() - start_time
            success = result.returncode == 0

            with open(log_file, "w") as f:
                f.write(f"=== {symbol} ===\n")
                f.write(f"Status: {'OK' if success else 'FAILED'}\n")
                f.write(f"Return code: {result.returncode}\n")
                f.write(f"Elapsed: {elapsed:.1f}s\n")
                f.write(f"\n=== STDOUT ===\n{result.stdout}\n")
                if result.stderr:
                    f.write(f"\n=== STDERR ===\n{result.stderr}\n")

            status = "OK" if success else "FAILED"
            print(f"[{status}] {symbol} ({elapsed:.1f}s)")

            return {
                "symbol": symbol,
                "success": success,
                "elapsed": elapsed,
                "returncode": result.returncode,
            }

        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            print(f"[TIMEOUT] {symbol} ({elapsed:.1f}s)")
            with open(log_file, "w") as f:
                f.write(f"=== {symbol} ===\n")
                f.write(f"Status: TIMEOUT after {elapsed:.1f}s\n")
            return {
                "symbol": symbol,
                "success": False,
                "elapsed": elapsed,
                "returncode": -1,
            }

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"[ERROR] {symbol}: {e}")
            with open(log_file, "w") as f:
                f.write(f"=== {symbol} ===\nStatus: ERROR\n{e}\n")
            return {
                "symbol": symbol,
                "success": False,
                "elapsed": elapsed,
                "returncode": -1,
            }


def run_pipeline(args: argparse.Namespace) -> int:
    """Run the LLM search pipeline from a YAML job file."""
    jobs = load_jobs(args.yaml_file)

    print(f"=== LLM Gene Search Pipeline ===")
    print(f"Jobs: {len(jobs)}")
    print(f"Model: {args.model}")
    print(f"Max workers: {args.max_workers}")
    print(f"Budget per agent: ${args.max_budget}")
    print(f"Timeout: {args.timeout}s")
    print()

    # Resolve prompts and check prerequisites
    resolved = []
    skipped = []
    for job in jobs:
        symbol = job["symbol"]
        mode = str(job["mode"]).lower()
        prompt, skip_reason = build_prompt_for_job(job)
        if skip_reason:
            print(f"  [SKIP] {symbol:20s} ({mode}) — {skip_reason}")
            skipped.append({"symbol": symbol, "mode": mode, "reason": skip_reason})
        else:
            print(f"  [QUEUE] {symbol:20s} ({mode})")
            resolved.append({"symbol": symbol, "mode": mode, "prompt": prompt})

    if args.dry_run:
        print(f"\nDry run — {len(resolved)} jobs queued, {len(skipped)} skipped.")
        return 0

    if not resolved:
        print("\nNo jobs to run.")
        return 0

    print()
    start_time = time.time()
    results = []
    semaphore = threading.Semaphore(args.max_workers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {}
        for job in resolved:
            future = executor.submit(
                run_agent,
                job["symbol"],
                job["prompt"],
                args.model,
                args.max_budget,
                args.timeout,
                semaphore,
            )
            futures[future] = job["symbol"]

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)

    total_elapsed = time.time() - start_time
    succeeded = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    print(f"\n{'=' * 50}")
    print(f"=== SUMMARY ===")
    print(f"Total time: {total_elapsed:.1f}s ({total_elapsed / 60:.1f}m)")
    print(f"Succeeded: {len(succeeded)}/{len(results)}")
    if skipped:
        print(f"Skipped: {len(skipped)}")
    if failed:
        print(f"Failed: {len(failed)}")
    print()
    for r in sorted(results, key=lambda x: x["symbol"]):
        status = "OK" if r["success"] else "FAIL"
        print(f"  [{status}] {r['symbol']:20s} {r['elapsed']:7.1f}s")

    # Write summary JSON
    summary_file = LOGS_DIR / "llm_search_summary.json"
    with open(summary_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "model": args.model,
                "total_elapsed": total_elapsed,
                "succeeded": len(succeeded),
                "failed": len(failed),
                "skipped": len(skipped),
                "results": results,
                "skipped_jobs": skipped,
            },
            f,
            indent=2,
        )
    print(f"\nSummary written to {summary_file}")

    return 0 if not failed else 1


def generate_config(args: argparse.Namespace) -> int:
    """Generate a YAML config from the database."""
    from processing.config import get_sspsygene_config

    config = get_sspsygene_config()
    db_path = config.out_db
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        print("Run 'sspsygene load-db' first.")
        return 1

    print(f"Querying top {args.top_n} genes from {db_path}...")
    genes = _get_top_genes(db_path, args.top_n)
    print(f"Found {len(genes)} unique genes across 4 ranking methods.")

    # Determine mode for each gene
    jobs = []
    for gene in genes:
        symbol = gene["human_symbol"]
        gene_file = GENE_RESULTS_DIR / f"{symbol}.json"
        mode = "verify" if gene_file.exists() else "new"
        job: dict = {"symbol": symbol, "mode": mode}
        if mode == "new":
            job["central_gene_id"] = gene["central_gene_id"]
        jobs.append(job)

    new_count = sum(1 for j in jobs if j["mode"] == "new")
    verify_count = sum(1 for j in jobs if j["mode"] == "verify")
    print(f"  new: {new_count}, verify: {verify_count}")

    # Build YAML output
    yaml_data = {"jobs": jobs}
    yaml_str = (
        "# Auto-generated LLM gene search config\n"
        f"# Generated: {datetime.now().isoformat()}\n"
        f"# Top-N: {args.top_n} ({len(genes)} unique genes)\n"
        "#\n"
        "# Usage:\n"
        "#   python run_llm_search.py llm_jobs.yaml\n"
        "#   python run_llm_search.py llm_jobs.yaml --dry-run\n"
        "#   python run_llm_search.py llm_jobs.yaml --model opus\n"
        "#\n"
        "# Modes: new, verify, update, verify_update\n"
        "\n"
    )
    yaml_str += yaml.dump(yaml_data, default_flow_style=False, sort_keys=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(yaml_str)
        print(f"Config written to {args.output}")
    else:
        print()
        print(yaml_str)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parallel LLM gene search orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Modes:
  new            Search from scratch (skips if file already exists)
  verify         Verify and correct existing data
  update         Amend existing data with new findings (trusts existing)
  verify_update  Verify existing data, then search for new findings

Examples:
  python run_llm_search.py llm_jobs.yaml
  python run_llm_search.py llm_jobs.yaml --model opus --max-workers 10
  python run_llm_search.py llm_jobs.yaml --dry-run
  python run_llm_search.py --generate-config --top-n 100 --output llm_jobs.yaml
""",
    )

    # Config generation mode
    parser.add_argument(
        "--generate-config",
        action="store_true",
        help="Generate a YAML config from the database instead of running jobs",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=50,
        help="Number of top genes per ranking method (default: 50)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file for generated config (default: stdout)",
    )

    # Pipeline mode
    parser.add_argument(
        "yaml_file",
        nargs="?",
        help="YAML file with pipeline jobs",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help=f"Max concurrent agents (default: {DEFAULT_MAX_WORKERS})",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        choices=VALID_MODELS,
        help=f"Claude model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--max-budget",
        type=str,
        default=DEFAULT_MAX_BUDGET,
        help=f"Max budget per agent in USD (default: {DEFAULT_MAX_BUDGET})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout per agent in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without executing",
    )

    args = parser.parse_args()

    # Ensure logs directory exists
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    GENE_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.generate_config:
        return generate_config(args)

    if not args.yaml_file:
        parser.error("yaml_file is required when not using --generate-config")

    # Verify settings file exists
    if not SETTINGS_FILE.exists():
        print(f"ERROR: Settings file not found at {SETTINGS_FILE}")
        print("Create processing/.claude/settings.json with agent permissions.")
        return 1

    return run_pipeline(args)


if __name__ == "__main__":
    sys.exit(main())
