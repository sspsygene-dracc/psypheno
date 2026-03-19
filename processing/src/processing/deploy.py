"""Deployment automation for SSPsyGene.

Automates the full deployment workflow:
  1. git push (local)
  2. Deploy production site on hgwdev (git pull, optionally load-db, npm run build)
  3. Deploy internal site on hgwdev (git pull, set env vars, optionally load-db, npm run build)
  4. Restart web servers on psygene (kill processes; systemd restarts them)
"""

from __future__ import annotations

import subprocess

import click

# ── Server / path configuration ──────────────────────────────────────────────

HGWDEV = "hgwdev"
PSYGENE = "psygene"
GIT_BRANCH = "main"

PROD_PATH = "/hive/groups/SSPsyGene/sspsygene_website"
INT_PATH = "/hive/groups/SSPsyGene/sspsygene_website_int"
PROD_ENV = {
    "SSPSYGENE_CONFIG_JSON": f"{PROD_PATH}/processing/src/processing/config.json",
    "SSPSYGENE_DATA_DIR": f"{PROD_PATH}/data",
    "SSPSYGENE_DATA_DB": f"{PROD_PATH}/data/db/sspsygene.db",
}
INT_ENV = {
    "SSPSYGENE_CONFIG_JSON": f"{INT_PATH}/processing/src/processing/config.json",
    "SSPSYGENE_DATA_DIR": f"{INT_PATH}/data",
    "SSPSYGENE_DATA_DB": "/cluster/home/jbirgmei/sspsygene_website_int/data/db/sspsygene.db",
}

CONDA_ENV = "sspsygene"
CONDA_INIT = "source $HOME/opt_rocky9/miniconda3/etc/profile.d/conda.sh"

# Timeouts (seconds)
LOCAL_TIMEOUT = 120
SSH_TIMEOUT = 600
BUILD_TIMEOUT = 900
LOAD_DB_TIMEOUT = 1800


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


def _step_pull_all(*, do_prod: bool, do_int: bool) -> None:
    """Pull latest code on all sites before any build/load-db steps.

    This ensures shared resources (e.g. the processing package installed
    from one site but used by both) are up-to-date before either site
    runs load-db or npm build.
    """
    click.secho("\n[2/4] Pulling latest code on hgwdev", bold=True)
    if do_prod:
        _run_ssh(HGWDEV, f"cd {PROD_PATH} && git pull", desc=f"git pull ({PROD_PATH})")
    if do_int:
        _run_ssh(HGWDEV, f"cd {INT_PATH} && git pull", desc=f"git pull ({INT_PATH})")


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


def run_deploy(
    *,
    load_db: bool = False,
    no_push: bool = False,
    prod_only: bool = False,
    int_only: bool = False,
    no_restart: bool = False,
) -> None:
    """Run the full deployment pipeline."""
    if prod_only and int_only:
        raise click.ClickException("--prod-only and --int-only are mutually exclusive.")

    do_prod = not int_only
    do_int = not prod_only

    _preflight_checks()

    # Step 1 — git push
    if no_push:
        click.secho("\n[1/4] Skipping git push (--no-push)", bold=True)
    else:
        _step_push()

    # Step 2 — git pull ALL sites first (the processing package may be
    # installed from one site but used by both, so both must be current)
    _step_pull_all(do_prod=True, do_int=True)

    # Step 3 — build/load-db per site
    if do_prod:
        click.secho("\n[3/4] Deploying production site on hgwdev", bold=True)
        _step_deploy_site(PROD_PATH, label="Production", load_db=load_db, env_vars=PROD_ENV)
    else:
        click.secho("\n[3/4] Skipping production site (--int-only)", bold=True)

    if do_int:
        click.secho("\n[3/4] Deploying internal site on hgwdev", bold=True)
        _step_deploy_site(INT_PATH, label="Internal", load_db=load_db, env_vars=INT_ENV)
    else:
        click.secho("\n[3/4] Skipping internal site (--prod-only)", bold=True)

    # Step 4 — restart web servers
    if no_restart:
        click.secho("\n[4/4] Skipping restart (--no-restart)", bold=True)
    else:
        _step_restart_psygene()

    click.secho("\nDeployment complete!", fg="green", bold=True)
