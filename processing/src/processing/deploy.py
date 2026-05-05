"""Deployment automation for SSPsyGene.

Automates the full deployment workflow:
  1. git push (local)
  2. Deploy production site on hgwdev (git pull, optionally load-db, npm run build)
  3. Deploy internal site on hgwdev (git pull, set env vars, optionally load-db, npm run build)
  4. Restart web servers on psygene (kill processes; systemd restarts them)
"""

from __future__ import annotations

import shlex
import subprocess

import click

# ── Server / path configuration ──────────────────────────────────────────────

HGWDEV = "hgwdev"
PSYGENE = "psygene"
GIT_BRANCH = "main"

PROD_PATH = "/hive/groups/SSPsyGene/sspsygene_website"
DEV_PATH = "/hive/groups/SSPsyGene/sspsygene_website_dev"
INT_PATH = "/hive/groups/SSPsyGene/sspsygene_website_int"


def _site_env(path: str) -> dict[str, str]:
    return {
        "SSPSYGENE_CONFIG_JSON": f"{path}/processing/src/processing/config.json",
        "SSPSYGENE_DATA_DIR": f"{path}/data",
        "SSPSYGENE_DATA_DB": f"{path}/data/db/sspsygene.db",
    }


PROD_ENV = _site_env(PROD_PATH)
DEV_ENV = _site_env(DEV_PATH)
INT_ENV = _site_env(INT_PATH)

# Canonical dev → int → prod ordering: deploys roll from lowest-stakes
# (dev) to highest-stakes (prod) regardless of the order the user lists.
INSTANCE_ORDER = ("dev", "int", "prod")
INSTANCE_PATHS = {"dev": DEV_PATH, "int": INT_PATH, "prod": PROD_PATH}
INSTANCE_ENVS = {"dev": DEV_ENV, "int": INT_ENV, "prod": PROD_ENV}
INSTANCE_LABELS = {"dev": "Dev", "int": "Internal", "prod": "Production"}

CONDA_ENV = "sspsygene"
CONDA_INIT = "source $HOME/opt_rocky9/miniconda3/etc/profile.d/conda.sh"

# Timeouts (seconds)
LOCAL_TIMEOUT = 120
SSH_TIMEOUT = 600
BUILD_TIMEOUT = 900
LOAD_DB_TIMEOUT = 1800
PREPROCESS_TIMEOUT = 1800


# ── Error handling ───────────────────────────────────────────────────────────


class DeployError(click.ClickException):
    """A deployment step failed."""

    def __init__(self, message: str, detail: str = "") -> None:
        self.detail = detail
        super().__init__(message)

    def format_message(self) -> str:
        msg = self.message
        if self.detail:
            indented = "\n".join(f"  {line}" for line in self.detail.splitlines())
            msg += "\n" + indented
        return msg


# ── Low-level helpers ────────────────────────────────────────────────────────


def _run_local(
    cmd: list[str], *, desc: str, timeout: int = LOCAL_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    """Run a local command; raise DeployError on failure."""
    click.echo(f"  -> {desc}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise DeployError(f"Timed out after {timeout}s: {desc}") from e
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise DeployError(f"Failed: {desc}", detail=output)
    return result


def _run_ssh(
    host: str,
    remote_cmd: str,
    *,
    desc: str,
    timeout: int = SSH_TIMEOUT,
    check: bool = True,
    stream: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a command on *host* via SSH; raise DeployError on failure."""
    click.echo(f"  -> [{host}] {desc}")
    try:
        if stream:
            proc = subprocess.run(
                ["ssh", "-t", host, remote_cmd],
                timeout=timeout,
            )
            result = subprocess.CompletedProcess(
                proc.args, proc.returncode, stdout="", stderr=""
            )
        else:
            result = subprocess.run(
                ["ssh", host, remote_cmd],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired as e:
        raise DeployError(f"Timed out after {timeout}s on {host}: {desc}") from e
    if check and result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise DeployError(f"Failed on {host}: {desc}", detail=output)
    return result


# ── Preflight checks ────────────────────────────────────────────────────────


def _preflight_checks() -> None:
    """Verify the local repo is clean and on the expected branch."""
    click.secho("Preflight checks", bold=True)

    # Uncommitted changes?
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise DeployError(
            "Working directory has uncommitted changes — commit or stash before deploying.",
            detail=result.stdout.strip(),
        )
    click.echo("  -> Working directory is clean")

    # Correct branch?
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    branch = result.stdout.strip()
    if branch != GIT_BRANCH:
        click.secho(
            f"  WARNING: On branch '{branch}', not '{GIT_BRANCH}'.",
            fg="yellow",
        )
        if not click.confirm("  Continue anyway?"):
            raise SystemExit(0)
    else:
        click.echo(f"  -> On branch {GIT_BRANCH}")


# ── Deployment steps ────────────────────────────────────────────────────────


def _step_push() -> None:
    click.secho("\n[1/4] Pushing local changes", bold=True)
    _run_local(["git", "push"], desc="git push")


def _step_pull_all(instances: list[str]) -> None:
    """Pull latest code on the selected sites before any build/load-db steps.

    This ensures shared resources (e.g. the processing package installed
    from one site but used by others) are up-to-date before any site
    runs load-db or npm build.
    """
    click.secho("\n[2/4] Pulling latest code on hgwdev", bold=True)
    for inst in instances:
        path = INSTANCE_PATHS[inst]
        _run_ssh(HGWDEV, f"cd {path} && git pull", desc=f"git pull ({path})")


def _step_preprocess_site(
    path: str,
    *,
    label: str,
    env_vars: dict[str, str],
) -> None:
    """Run every dataset's preprocess.py under the conda env. Aborts on first failure."""
    click.echo(f"\n  --- {label} preprocess ({path}) ---")
    env_prefix = " ".join(f"{k}={v}" for k, v in env_vars.items()) + " "
    inner = (
        "set -e; "
        'for d in data/datasets/*/; do '
        '  if [ -f "$d/preprocess.py" ]; then '
        '    echo "[preprocess] $d"; '
        '    (cd "$d" && python preprocess.py); '
        "  fi; "
        "done"
    )
    cmd = (
        f"cd {path} && {CONDA_INIT} && "
        f"{env_prefix}conda run --no-capture-output -n {CONDA_ENV} bash -c {shlex.quote(inner)}"
    )
    _run_ssh(
        HGWDEV,
        cmd,
        desc="Running per-dataset preprocess.py scripts",
        timeout=PREPROCESS_TIMEOUT,
        stream=True,
    )


def _step_deploy_site(
    path: str,
    *,
    label: str,
    load_db: bool,
    env_vars: dict[str, str] | None = None,
) -> None:
    """Optionally rebuild DB, and build the web app on hgwdev."""
    click.echo(f"\n  --- {label} ({path}) ---")

    if load_db:
        env_prefix = ""
        if env_vars:
            env_prefix = " ".join(f"{k}={v}" for k, v in env_vars.items()) + " "
        cmd = (
            f"cd {path} && "
            f"{CONDA_INIT} && "
            f"{env_prefix}conda run --no-capture-output -n {CONDA_ENV} sspsygene load-db"
        )
        _run_ssh(
            HGWDEV,
            cmd,
            desc="sspsygene load-db (this may take a while)",
            timeout=LOAD_DB_TIMEOUT,
            stream=True,
        )

    _run_ssh(
        HGWDEV,
        f"cd {path}/web && npm run build",
        desc="npm run build (this may take a few minutes)",
        timeout=BUILD_TIMEOUT,
    )


def _step_restart_psygene() -> None:
    """Find and kill Next.js / npm processes on psygene so systemd restarts them."""
    click.secho("\n[4/4] Restarting web servers on psygene", bold=True)

    result = _run_ssh(
        PSYGENE,
        "ps aux | grep -E 'next-server|npm.*3110' | grep -v grep | grep \"^$USER \"",
        desc="Finding Next.js / npm processes",
        check=False,
    )

    if not result.stdout.strip():
        click.secho(
            "  No running Next.js / npm processes found on psygene — nothing to restart.",
            fg="yellow",
        )
        return

    lines = result.stdout.strip().splitlines()
    pids: list[str] = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 2:
            pids.append(parts[1])

    if not pids:
        click.secho("  Could not parse PIDs from process list.", fg="yellow")
        return

    click.echo(f"  Found {len(pids)} process(es):")
    for line in lines:
        click.echo(f"    {line}")

    _run_ssh(PSYGENE, f"kill {' '.join(pids)}", desc=f"Killing {len(pids)} process(es)")
    click.echo("  Processes killed — systemd should restart them automatically.")


# ── Main entry point ────────────────────────────────────────────────────────


def _resolve_instances(instances: str | None) -> list[str]:
    """Parse the --instances string and return a list in canonical dev→int→prod order.

    Accepts None (= all three) or a comma-separated subset. Unknown tokens raise
    ClickException; duplicates are deduped silently.
    """
    if instances is None:
        return list(INSTANCE_ORDER)
    tokens = [t.strip() for t in instances.split(",") if t.strip()]
    if not tokens:
        raise click.ClickException(
            "--instances must list at least one of: " + ", ".join(INSTANCE_ORDER)
        )
    valid = set(INSTANCE_ORDER)
    unknown = sorted({t for t in tokens if t not in valid})
    if unknown:
        raise click.ClickException(
            f"Unknown --instances value(s): {', '.join(unknown)}. "
            f"Valid: {', '.join(INSTANCE_ORDER)}."
        )
    requested = set(tokens)
    return [i for i in INSTANCE_ORDER if i in requested]


def run_deploy(
    *,
    load_db: bool = False,
    no_push: bool = False,
    instances: str | None = None,
    restart: bool = False,
    preprocess: bool = False,
) -> None:
    """Run the full deployment pipeline."""
    selected = _resolve_instances(instances)

    _preflight_checks()

    # Step 1 — git push
    if no_push:
        click.secho("\n[1/4] Skipping git push (--no-push)", bold=True)
    else:
        _step_push()

    # Step 2 — git pull selected sites first (the processing package may be
    # installed from one site but used by others, so all selected must be
    # current before any runs load-db or npm build).
    _step_pull_all(selected)

    # Step 3 — build/load-db per site (canonical dev → int → prod order)
    if preprocess:
        click.secho("\n[3a/4] Running preprocess.py on selected sites", bold=True)
        for inst in selected:
            _step_preprocess_site(
                INSTANCE_PATHS[inst],
                label=INSTANCE_LABELS[inst],
                env_vars=INSTANCE_ENVS[inst],
            )

    click.secho("\n[3/4] Deploying sites on hgwdev", bold=True)
    for inst in selected:
        _step_deploy_site(
            INSTANCE_PATHS[inst],
            label=INSTANCE_LABELS[inst],
            load_db=load_db,
            env_vars=INSTANCE_ENVS[inst],
        )

    # Step 4 — restart web servers (default is no restart; the web process
    # auto-detects DB changes via inode/mtime check in web/lib/db.ts, so
    # only pass --restart when JS code has changed).
    if restart:
        _step_restart_psygene()
    else:
        click.secho(
            "\n[4/4] Skipping restart (default). The web process auto-detects DB",
            bold=True,
        )
        click.echo("      changes; pass --restart if JS code changed and needs reloading.")

    click.secho("\nDeployment complete!", fg="green", bold=True)
