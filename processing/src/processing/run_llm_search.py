"""Parallel LLM gene search orchestrator.

Reads a YAML job file and launches parallel Claude CLI agents, each
researching one gene for neuropsychiatric associations. Each agent writes
its result directly to data/llm_gene_results/{SYMBOL}.json.
"""

import concurrent.futures
import functools
import json
import os
import signal
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from tqdm import tqdm

from processing.config import get_sspsygene_config
from processing.llm_search import (
    VALID_MODES,
    build_new_prompt,
    build_update_prompt,
    build_verify_prompt,
    build_verify_update_prompt,
    get_top_genes,
    load_gene_result,
)

# Force unbuffered stdout so log lines appear immediately
# pylint: disable=redefined-builtin
print = functools.partial(print, flush=True)  # type: ignore[assignment]

PACKAGE_DIR = Path(__file__).resolve().parent
PROCESSING_DIR = PACKAGE_DIR.parents[1]
PROJECT_ROOT = PROCESSING_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
GENE_RESULTS_DIR = DATA_DIR / "llm_gene_results"
LOGS_DIR = PROCESSING_DIR / "logs"
SETTINGS_FILE = PROCESSING_DIR / ".claude" / "settings.json"

# Defaults
DEFAULT_MAX_WORKERS = 20
DEFAULT_TIMEOUT = 360  # 6 minutes per gene
DEFAULT_MAX_BUDGET = "2.00"
DEFAULT_MODEL = "sonnet"
VALID_MODELS = ("sonnet", "opus")


def load_jobs(yaml_path: str) -> list[dict[str, Any]]:
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


def build_prompt_for_job(
    job: dict[str, Any],
    symbol_to_central_gene_id: dict[str, int] | None = None,
) -> tuple[str, str | None]:
    """Build the agent prompt for a job. Returns (prompt, skip_reason)."""
    symbol = job["symbol"]
    mode = str(job["mode"]).lower()
    gene_file = GENE_RESULTS_DIR / f"{symbol}.json"
    gene_file_path = str(gene_file)

    # For 'new' mode, skip if file already exists
    if mode == "new":
        if gene_file.exists():
            return "", "file already exists (mode=new skips existing)"
        central_gene_id = None
        if symbol_to_central_gene_id is not None:
            central_gene_id = symbol_to_central_gene_id.get(symbol)
        if central_gene_id is None:
            central_gene_id = job.get("central_gene_id")
        if central_gene_id is None:
            return "", "symbol not found in central_gene table"
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
    if mode == "update":
        return (
            build_update_prompt(symbol, central_gene_id, gene_file_path, existing_data),
            None,
        )
    if mode == "verify_update":
        return (
            build_verify_update_prompt(
                symbol, central_gene_id, gene_file_path, existing_data
            ),
            None,
        )

    return "", f"unknown mode '{mode}'"


def _load_symbol_to_central_gene_id(db_path: Path) -> dict[str, int]:
    """Load stable symbol->central_gene_id mapping from the database."""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT human_symbol, id FROM central_gene WHERE human_symbol IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return {str(symbol): int(gene_id) for symbol, gene_id in rows}


def run_agent(
    symbol: str,
    prompt: str,
    model: str,
    max_budget: str,
    timeout: int,
    semaphore: threading.Semaphore,
    abort_event: threading.Event,
    active_processes: dict[str, subprocess.Popen[str]],
    active_processes_lock: threading.Lock,
) -> dict[str, Any]:
    """Run a single gene search agent via Claude CLI."""
    start_time = time.time()
    log_file = LOGS_DIR / f"{symbol}.log"

    with semaphore:
        if abort_event.is_set():
            return {
                "symbol": symbol,
                "status": "ABORTED",
                "success": False,
                "elapsed": 0.0,
                "returncode": -2,
            }

        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                [
                    "claude",
                    "-p",
                    "--model",
                    model,
                    "--max-budget-usd",
                    max_budget,
                    "--settings",
                    str(SETTINGS_FILE),
                    prompt,
                ],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    **{k: v for k, v in os.environ.items() if k != "CLAUDECODE"},
                    "CLAUDE_CODE_ENTRYPOINT": "cli",
                },
            )
            with active_processes_lock:
                active_processes[symbol] = process

            stdout, stderr = process.communicate(timeout=timeout)
            returncode = process.returncode
            if returncode is None:
                returncode = -1

            elapsed = time.time() - start_time
            success = returncode == 0

            with open(log_file, "w") as f:
                f.write(f"=== {symbol} ===\n")
                f.write(f"Status: {'OK' if success else 'FAILED'}\n")
                f.write(f"Return code: {returncode}\n")
                f.write(f"Elapsed: {elapsed:.1f}s\n")
                f.write(f"\n=== STDOUT ===\n{stdout}\n")
                if stderr:
                    f.write(f"\n=== STDERR ===\n{stderr}\n")

            result_status = (
                "ABORTED"
                if abort_event.is_set() and returncode != 0
                else ("OK" if success else "FAILED")
            )

            return {
                "symbol": symbol,
                "status": result_status,
                "success": success,
                "elapsed": elapsed,
                "returncode": returncode,
            }

        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            if process is not None:
                process.kill()
                process.communicate()
            print(f"[TIMEOUT] {symbol} ({elapsed:.1f}s)")
            with open(log_file, "w") as f:
                f.write(f"=== {symbol} ===\n")
                f.write(f"Status: TIMEOUT after {elapsed:.1f}s\n")
            return {
                "symbol": symbol,
                "status": "TIMEOUT",
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
                "status": "ERROR",
                "success": False,
                "elapsed": elapsed,
                "returncode": -1,
            }
        finally:
            with active_processes_lock:
                active_processes.pop(symbol, None)


def run_pipeline(
    yaml_file: str,
    model: str = DEFAULT_MODEL,
    max_workers: int = DEFAULT_MAX_WORKERS,
    max_budget: str = DEFAULT_MAX_BUDGET,
    timeout: int = DEFAULT_TIMEOUT,
    dry_run: bool = False,
) -> int:
    """Run the LLM search pipeline from a YAML job file.

    Returns 0 on success, 1 if any jobs failed.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    GENE_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if not SETTINGS_FILE.exists():
        print(f"ERROR: Settings file not found at {SETTINGS_FILE}")
        print("Create processing/.claude/settings.json with agent permissions.")
        return 1

    jobs = load_jobs(yaml_file)
    config = get_sspsygene_config()
    db_path = config.out_db
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        print("Run 'sspsygene load-db' first.")
        return 1
    symbol_to_central_gene_id = _load_symbol_to_central_gene_id(db_path)

    print("=== LLM Gene Search Pipeline ===")
    print(f"Jobs: {len(jobs)}")
    print(f"Model: {model}")
    print(f"Max workers: {max_workers}")
    print(f"Budget per agent: ${max_budget}")
    print(f"Timeout: {timeout}s")
    print()

    # Resolve prompts and check prerequisites
    resolved = []
    skipped = []
    for job in jobs:
        symbol = job["symbol"]
        mode = str(job["mode"]).lower()
        prompt, skip_reason = build_prompt_for_job(job, symbol_to_central_gene_id)
        if skip_reason:
            print(f"  [SKIP] {symbol:20s} ({mode}) - {skip_reason}")
            skipped.append({"symbol": symbol, "mode": mode, "reason": skip_reason})
        else:
            print(f"  [QUEUE] {symbol:20s} ({mode})")
            resolved.append({"symbol": symbol, "mode": mode, "prompt": prompt})

    if dry_run:
        print(f"\nDry run - {len(resolved)} jobs queued, {len(skipped)} skipped.")
        return 0

    if not resolved:
        print("\nNo jobs to run.")
        return 0

    print()
    start_time = time.time()
    results: list[dict[str, Any]] = []
    semaphore = threading.Semaphore(max_workers)
    abort_event = threading.Event()
    force_abort_event = threading.Event()
    active_processes: dict[str, subprocess.Popen[str]] = {}
    active_processes_lock = threading.Lock()
    sigint_count = 0

    def _kill_running_agents() -> None:
        with active_processes_lock:
            running = list(active_processes.items())
        if not running:
            print("  No active sub-agents to terminate.")
            return

        for running_symbol, process in running:
            try:
                if process.poll() is None:
                    process.kill()
                    print(f"  [KILL] Killed {running_symbol} (pid={process.pid})")
            except Exception as e:
                print(f"  [WARN] Could not terminate {running_symbol}: {e}")

    def _handle_sigint(_signum: int, _frame: Any) -> None:
        nonlocal sigint_count
        sigint_count += 1
        if sigint_count == 1:
            print(
                "\n[WARN] Ctrl-C received. Press Ctrl-C again to abort the run "
                "and kill all running sub-agents."
            )
            return

        print(
            "\n[ABORT] Second Ctrl-C received. Aborting run and killing "
            "all running sub-agents..."
        )
        abort_event.set()
        force_abort_event.set()
        _kill_running_agents()

    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _handle_sigint)

    ok_count = 0
    fail_count = 0

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for job in resolved:
                future = executor.submit(
                    run_agent,
                    job["symbol"],
                    job["prompt"],
                    model,
                    max_budget,
                    timeout,
                    semaphore,
                    abort_event,
                    active_processes,
                    active_processes_lock,
                )
                futures[future] = job["symbol"]

            with tqdm(
                total=len(futures),
                desc="Genes",
                unit="gene",
            ) as pbar:
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    results.append(result)
                    if result["success"]:
                        ok_count += 1
                    else:
                        fail_count += 1
                    pbar.set_description(
                        f"[{result['status']}] {result['symbol']:12s}"
                    )
                    pbar.set_postfix_str(f"OK:{ok_count} FAIL:{fail_count}")
                    pbar.update(1)
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)

    total_elapsed = time.time() - start_time
    succeeded = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    aborted = [r for r in results if r["returncode"] == -2]

    print(f"\n{'=' * 50}")
    print("=== SUMMARY ===")
    print(f"Total time: {total_elapsed:.1f}s ({total_elapsed / 60:.1f}m)")
    print(f"Succeeded: {len(succeeded)}/{len(results)}")
    if skipped:
        print(f"Skipped: {len(skipped)}")
    if failed:
        print(f"Failed: {len(failed)}")
    if aborted:
        print(f"Aborted before start: {len(aborted)}")
    print()
    for r in sorted(results, key=lambda x: x["symbol"]):
        status = "ABORT" if r["returncode"] == -2 else ("OK" if r["success"] else "FAIL")
        print(f"  [{status}] {r['symbol']:20s} {r['elapsed']:7.1f}s")

    # Write summary JSON
    summary_file = LOGS_DIR / "llm_search_summary.json"
    with open(summary_file, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "model": model,
                "total_elapsed": total_elapsed,
                "succeeded": len(succeeded),
                "failed": len(failed),
                "skipped": len(skipped),
                "aborted_before_start": len(aborted),
                "results": results,
                "skipped_jobs": skipped,
            },
            f,
            indent=2,
        )
    print(f"\nSummary written to {summary_file}")

    if force_abort_event.is_set():
        return 130
    return 0 if not failed else 1


def generate_config(
    top_n: int = 50,
    output: str | None = None,
) -> int:
    """Generate a YAML config from the database.

    Returns 0 on success, 1 on error.
    """
    GENE_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    config = get_sspsygene_config()
    db_path = config.out_db
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        print("Run 'sspsygene load-db' first.")
        return 1

    print(f"Querying top {top_n} genes from {db_path}...")
    genes = get_top_genes(db_path, top_n)
    print(f"Found {len(genes)} unique genes across 4 ranking methods.")

    # Determine mode for each gene
    jobs = []
    for gene in genes:
        symbol = gene["human_symbol"]
        gene_file = GENE_RESULTS_DIR / f"{symbol}.json"
        mode = "verify" if gene_file.exists() else "new"
        job: dict[str, Any] = {"symbol": symbol, "mode": mode}
        jobs.append(job)

    new_count = sum(1 for j in jobs if j["mode"] == "new")
    verify_count = sum(1 for j in jobs if j["mode"] == "verify")
    print(f"  new: {new_count}, verify: {verify_count}")

    # Build YAML output
    yaml_data = {"jobs": jobs}
    yaml_str = (
        "# Auto-generated LLM gene search config\n"
        f"# Generated: {datetime.now().isoformat()}\n"
        f"# Top-N: {top_n} ({len(genes)} unique genes)\n"
        "#\n"
        "# Usage:\n"
        "#   sspsygene run-llm-search llm_jobs.yaml\n"
        "#   sspsygene run-llm-search llm_jobs.yaml --dry-run\n"
        "#   sspsygene run-llm-search llm_jobs.yaml --model opus\n"
        "#\n"
        "# Modes: new, verify, update, verify_update\n"
        "\n"
    )
    yaml_str += yaml.dump(yaml_data, default_flow_style=False, sort_keys=False)

    if output:
        with open(output, "w") as f:
            f.write(yaml_str)
        print(f"Config written to {output}")
    else:
        print()
        print(yaml_str)

    return 0
