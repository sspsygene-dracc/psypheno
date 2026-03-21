"""Notify data wranglers about config.yaml format changes.

Analyzes git commits touching config-related files since a given date,
then launches two parallel Claude CLI agents:
1. Email agent — drafts a summary email for wranglers
2. Docs agent — suggests updates to docs/adding-datasets.md
3. Dev docs agent — suggests updates to development.md
"""

import concurrent.futures
import functools
import os
import subprocess
import time
from datetime import date
from pathlib import Path

# pylint: disable=redefined-builtin
print = functools.partial(print, flush=True)  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATE_FILE = PROJECT_ROOT / ".last-wrangler-notify"

# Paths to watch for config-related changes
CONFIG_PATHS = [
    "data/datasets/*/config.yaml",
    "data/datasets/globals.yaml",
    "processing/src/processing/config.py",
    "processing/src/processing/types/*.py",
    "docs/adding-datasets.md",
    "server-architecture.md",
    "development.md",
    "README.md",
]

EMAIL_PROMPT_TEMPLATE = """\
You are an assistant helping maintain the SSPSyGene neuropsychiatric genetics \
data platform. Data wranglers maintain config.yaml files for datasets.

Below are git commits and diffs touching config-related files since {since_date}. \
Your job is to analyze these changes and draft an email to the data wranglers \
summarizing what changed in the config.yaml FORMAT or SCHEMA.

IMPORTANT GUIDELINES:
- Focus on STRUCTURAL changes: new fields, renamed fields, removed fields, \
changed validation rules, new required fields, deprecated fields, changes to \
allowed values, changes to how existing fields are interpreted.
- IGNORE content-only changes like new datasets being added, updated data \
values, new maintainer entries, or changelog entries — unless they illustrate \
a new required field.
- If there are NO structural/format changes, say so clearly and keep the \
email very short.
- Include before/after YAML examples where helpful.
- Be concise, friendly, and actionable.
- Format the email in markdown with a clear subject line at the top.

GIT CHANGES:
{changes}
"""

DOCS_PROMPT_TEMPLATE = """\
You are an assistant helping maintain the SSPSyGene neuropsychiatric genetics \
data platform. Data wranglers maintain config.yaml files for datasets, and \
docs/adding-datasets.md is their reference documentation.

Below are:
1. Git commits and diffs touching config-related files since {since_date}
2. The current contents of docs/adding-datasets.md

Your job is to suggest specific updates to docs/adding-datasets.md so the documentation \
stays accurate and up-to-date with the current config.yaml schema.

IMPORTANT GUIDELINES:
- Focus on ensuring the documentation matches the CURRENT config schema after \
the changes.
- Show your suggestions as concrete text — either a unified diff or rewritten \
sections with clear markers for what to add/remove/change.
- If docs/adding-datasets.md is empty or doesn't exist yet, write a complete initial \
draft documenting the config.yaml format based on what you can infer from the \
diffs and commit messages.
- If no documentation changes are needed, say so clearly.

GIT CHANGES:
{changes}

CURRENT docs/adding-datasets.md CONTENT:
{wranglers_md}
"""

DEV_DOCS_PROMPT_TEMPLATE = """\
You are an assistant helping maintain the SSPSyGene neuropsychiatric genetics \
data platform. development.md is the developer-facing documentation covering \
setup, architecture, and workflows.

Below are:
1. Git commits and diffs touching config-related files since {since_date}
2. The current contents of development.md

Your job is to suggest specific updates to development.md so the documentation \
stays accurate and up-to-date with any changes to config loading, processing \
pipeline behavior, config.yaml schema, or development workflows.

IMPORTANT GUIDELINES:
- Focus on ensuring the documentation matches the CURRENT state after the changes.
- Show your suggestions as concrete text — either a unified diff or rewritten \
sections with clear markers for what to add/remove/change.
- If development.md is empty or doesn't exist yet, write a complete initial \
draft based on what you can infer from the diffs and commit messages.
- If no documentation changes are needed, say so clearly.

GIT CHANGES:
{changes}

CURRENT development.md CONTENT:
{dev_md}
"""


def get_config_changes_since(since_date: str, repo_root: Path) -> str:
    """Get git log and diffs for config-related files since a date."""
    summary_cmd = [
        "git", "log", f"--since={since_date}", "--oneline", "--"
    ] + CONFIG_PATHS

    diff_cmd = [
        "git", "log", f"--since={since_date}", "-p", "--"
    ] + CONFIG_PATHS

    summary = subprocess.run(
        summary_cmd, cwd=repo_root, capture_output=True, text=True
    )
    diffs = subprocess.run(
        diff_cmd, cwd=repo_root, capture_output=True, text=True
    )

    if not summary.stdout.strip() and not diffs.stdout.strip():
        return ""

    return (
        f"=== COMMIT SUMMARY ===\n{summary.stdout}\n\n"
        f"=== FULL DIFFS ===\n{diffs.stdout}"
    )


def run_claude_agent(
    prompt: str, repo_root: Path, timeout: int, label: str
) -> str:
    """Run a Claude CLI agent and return its stdout."""
    start = time.time()
    print(f"[{label}] Starting Claude agent...")

    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [
                "claude",
                "-p",
                "--model", "opus",
                prompt,
            ],
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={
                **{k: v for k, v in os.environ.items() if k != "CLAUDECODE"},
                "CLAUDE_CODE_ENTRYPOINT": "cli",
            },
        )
        stdout, stderr = process.communicate(timeout=timeout)
        elapsed = time.time() - start

        if process.returncode != 0:
            print(f"[{label}] Agent failed (rc={process.returncode}, {elapsed:.1f}s)")
            if stderr:
                print(f"[{label}] stderr: {stderr[:500]}")
            return f"[Agent failed with return code {process.returncode}]\n{stderr}"

        print(f"[{label}] Done ({elapsed:.1f}s)")
        return stdout

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        if process is not None:
            process.kill()
            process.communicate()
        print(f"[{label}] Timed out after {elapsed:.1f}s")
        return f"[Agent timed out after {elapsed:.1f}s]"

    except Exception as e:
        print(f"[{label}] Error: {e}")
        return f"[Agent error: {e}]"


def run_email_agent(
    changes: str, since_date: str, repo_root: Path, timeout: int
) -> str:
    """Launch the email-drafting agent."""
    prompt = EMAIL_PROMPT_TEMPLATE.format(
        since_date=since_date, changes=changes
    )
    return run_claude_agent(prompt, repo_root, timeout, "EMAIL")


def run_docs_agent(
    changes: str, since_date: str, wranglers_md: str,
    repo_root: Path, timeout: int
) -> str:
    """Launch the adding-datasets docs-suggestion agent."""
    prompt = DOCS_PROMPT_TEMPLATE.format(
        since_date=since_date,
        changes=changes,
        wranglers_md=wranglers_md if wranglers_md else "(file does not exist yet)",
    )
    return run_claude_agent(prompt, repo_root, timeout, "DOCS")


def run_dev_docs_agent(
    changes: str, since_date: str, dev_md: str,
    repo_root: Path, timeout: int
) -> str:
    """Launch the development.md docs-suggestion agent."""
    prompt = DEV_DOCS_PROMPT_TEMPLATE.format(
        since_date=since_date,
        changes=changes,
        dev_md=dev_md if dev_md else "(file does not exist yet)",
    )
    return run_claude_agent(prompt, repo_root, timeout, "DEV-DOCS")


def load_last_notified_date(state_file: Path) -> str | None:
    """Read the last notification date from the state file."""
    if state_file.exists():
        return state_file.read_text().strip()
    return None


def save_last_notified_date(state_file: Path) -> None:
    """Write today's date to the state file."""
    state_file.write_text(date.today().isoformat() + "\n")


def run_notify(
    since: str | None,
    output_dir: Path,
    timeout: int,
) -> None:
    """Main orchestrator for the notify-wranglers command."""
    repo_root = PROJECT_ROOT

    # 1. Determine since_date
    if since:
        since_date = since
    else:
        since_date = load_last_notified_date(STATE_FILE)
        if not since_date:
            raise ValueError(
                "No --since date provided and no prior run found. "
                "Run with --since YYYY-MM-DD for the first time."
            )
    print(f"Looking for config changes since {since_date}...")

    # 2. Get git changes
    changes = get_config_changes_since(since_date, repo_root)
    if not changes:
        print("No config-related changes found in the given period.")
        return

    # 3. Read doc files if they exist
    wranglers_path = repo_root / "docs/adding-datasets.md"
    wranglers_md = ""
    if wranglers_path.exists():
        wranglers_md = wranglers_path.read_text()

    dev_docs_path = repo_root / "development.md"
    dev_md = ""
    if dev_docs_path.exists():
        dev_md = dev_docs_path.read_text()

    # 4. Launch all three agents in parallel
    print("Launching email, docs, and dev-docs agents in parallel...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        email_future = executor.submit(
            run_email_agent, changes, since_date, repo_root, timeout
        )
        docs_future = executor.submit(
            run_docs_agent, changes, since_date, wranglers_md, repo_root, timeout
        )
        dev_docs_future = executor.submit(
            run_dev_docs_agent, changes, since_date, dev_md, repo_root, timeout
        )

        email_result = email_future.result()
        docs_result = docs_future.result()
        dev_docs_result = dev_docs_future.result()

    # 5. Write outputs
    output_dir.mkdir(parents=True, exist_ok=True)

    email_path = output_dir / "email_draft.md"
    email_path.write_text(email_result)
    print(f"Email draft written to: {email_path}")

    docs_path = output_dir / "adding-datasets_suggestions.md"
    docs_path.write_text(docs_result)
    print(f"Doc suggestions written to: {docs_path}")

    dev_docs_out = output_dir / "development_suggestions.md"
    dev_docs_out.write_text(dev_docs_result)
    print(f"Dev doc suggestions written to: {dev_docs_out}")

    # 6. Save state
    save_last_notified_date(STATE_FILE)
    print(f"Last-notified date saved to: {STATE_FILE}")
    print("Done! Review the output files before sending.")
