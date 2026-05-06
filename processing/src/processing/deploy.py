"""Deployment automation for SSPsyGene.

Automates the full deployment workflow (canonical dev → int → prod order):
  1. git push (local)
  2. git pull on each selected site (hgwdev)
  3. Per-site preprocess.py (optional, --preprocess), load-db (optional,
     --load-db), npm ci + npm run build (hgwdev)
  4. Restart web servers on psygene for the deployed instances (optional,
     --restart) — runs BEFORE tests so e2e hits the new build
  5. Run scripts/test.sh all on each deployed site (optional, --run-tests)
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
        # Force `import processing` to resolve to THIS site's checkout. The
        # conda env's editable install pins the package to whichever site
        # was last `pip install -e .`'d (currently int) — without this
        # override, load-db / preprocess.py / pytest for dev or prod would
        # silently run int's code, which can mismatch the deploying site's
        # config schema.
        "PYTHONPATH": f"{path}/processing/src",
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
INSTANCE_E2E_URLS = {
    "dev": "https://psypheno-dev.gi.ucsc.edu",
    "int": "https://psypheno-int.gi.ucsc.edu",
    "prod": "https://psypheno.gi.ucsc.edu",
}
# Ports each instance's `npm start` listens on (Apache reverse-proxies the
# public URL to localhost:PORT). Used by _step_restart_psygene to target
# only the deployed instance(s) rather than killing every Next.js process.
INSTANCE_PORTS = {"dev": 3112, "int": 3111, "prod": 3110}

CONDA_ENV = "sspsygene"
CONDA_INIT = "source $HOME/opt_rocky9/miniconda3/etc/profile.d/conda.sh"

# Timeouts (seconds)
LOCAL_TIMEOUT = 120
SSH_TIMEOUT = 600
BUILD_TIMEOUT = 900
LOAD_DB_TIMEOUT = 1800
PREPROCESS_TIMEOUT = 1800
TEST_TIMEOUT = 1800


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
    click.secho("\n[1/5] Pushing local changes", bold=True)
    _run_local(["git", "push"], desc="git push")


def _step_pull_all(instances: list[str]) -> None:
    """Pull latest code on the selected sites before any build/load-db steps.

    This ensures shared resources (e.g. the processing package installed
    from one site but used by others) are up-to-date before any site
    runs load-db or npm build.
    """
    click.secho("\n[2/5] Pulling latest code on hgwdev", bold=True)
    for inst in instances:
        path = INSTANCE_PATHS[inst]
        _run_ssh(PSYGENE, f"cd {path} && git pull", desc=f"git pull ({path})")


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
        PSYGENE,
        cmd,
        desc="Running per-dataset preprocess.py scripts",
        timeout=PREPROCESS_TIMEOUT,
        stream=True,
    )


def _step_run_tests_site(
    path: str,
    *,
    label: str,
    base_url: str,
    env_vars: dict[str, str],
) -> None:
    """Run scripts/test.sh all on a deployed site, with playwright pointed
    at the deployed URL. Aborts on first failure (raises DeployError)."""
    click.echo(f"\n  --- {label} tests ({path}) ---")
    test_env = {
        **env_vars,
        "E2E_BASE_URL": base_url,
        "SSPSYGENE_TEST_HOMOLOGY_DIR": f"{path}/data/homology",
    }
    env_prefix = " ".join(f"{k}={v}" for k, v in test_env.items()) + " "
    inner = (
        "set -e; "
        # Hand scripts/test.sh the conda env's pytest — the local default of
        # processing/.venv-claude/bin/pytest doesn't exist on hgwdev.
        'PYTEST="$(command -v pytest)" '
        f"{env_prefix}"
        "scripts/test.sh all"
    )
    cmd = (
        f"cd {path} && {CONDA_INIT} && "
        f"conda run --no-capture-output -n {CONDA_ENV} bash -c {shlex.quote(inner)}"
    )
    _run_ssh(
        PSYGENE,
        cmd,
        desc="Running scripts/test.sh all (python + web + e2e + data-corr)",
        timeout=TEST_TIMEOUT,
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
            PSYGENE,
            cmd,
            desc="sspsygene load-db (this may take a while)",
            timeout=LOAD_DB_TIMEOUT,
            stream=True,
        )

    # Sync npm deps from package-lock.json before building so a package.json
    # bump in the just-pulled commit doesn't get built against a stale
    # node_modules. `npm ci` is deterministic — it wipes node_modules and
    # installs strictly from the lockfile.
    _run_ssh(
        PSYGENE,
        f"cd {path}/web && npm ci",
        desc="npm ci (deterministic install from package-lock.json)",
        timeout=BUILD_TIMEOUT,
        stream=True,
    )

    _run_ssh(
        PSYGENE,
        f"cd {path}/web && npm run build",
        desc="npm run build (this may take a few minutes)",
        timeout=BUILD_TIMEOUT,
    )


def _step_restart_psygene(instances: list[str]) -> None:
    """Restart Next.js processes on psygene for the given instances.

    Kills the `npm start --port NNNN` parents matching each instance's port;
    systemd respawns the unit (which terminates the next-server child along
    with it). Then waits for each instance's public URL to respond before
    returning, so subsequent steps (e.g. e2e tests) don't race the restart.
    """
    import time

    ports = [INSTANCE_PORTS[i] for i in instances]
    labels = ", ".join(INSTANCE_LABELS[i] for i in instances)
    click.secho(f"\n[4/5] Restarting web servers on psygene ({labels})", bold=True)

    port_alts = "|".join(str(p) for p in ports)
    grep_cmd = (
        "ps -fu \"$USER\" | "
        f"grep -E 'npm start --port ({port_alts})' | "
        "grep -v grep"
    )
    result = _run_ssh(
        PSYGENE,
        grep_cmd,
        desc=f"Finding npm processes for ports {', '.join(str(p) for p in ports)}",
        check=False,
    )

    if not result.stdout.strip():
        click.secho(
            f"  No running npm processes found for {labels} — nothing to restart.",
            fg="yellow",
        )
    else:
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

        _run_ssh(
            PSYGENE,
            f"kill {' '.join(pids)}",
            desc=f"Killing {len(pids)} process(es)",
        )
        click.echo("  Processes killed — systemd should restart them automatically.")

    # Wait for each instance's public URL to come back. systemd respawn is
    # usually quick (<5s) but the first request after restart can take a
    # few seconds while Next.js warms up.
    for inst in instances:
        url = f"{INSTANCE_E2E_URLS[inst]}/api/full-datasets"
        click.echo(f"  Waiting for {INSTANCE_LABELS[inst]} ({url}) to respond...")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            probe = subprocess.run(
                ["curl", "-fsS", "--max-time", "5", url],
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0:
                click.echo(f"    -> {INSTANCE_LABELS[inst]} is up.")
                break
            time.sleep(2)
        else:
            raise DeployError(
                f"Timed out after 60s waiting for {INSTANCE_LABELS[inst]} to respond at {url}"
            )


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
    run_tests: bool = False,
) -> None:
    """Run the full deployment pipeline."""
    selected = _resolve_instances(instances)

    _preflight_checks()

    # Step 1 — git push
    if no_push:
        click.secho("\n[1/5] Skipping git push (--no-push)", bold=True)
    else:
        _step_push()

    # Step 2 — git pull selected sites first (the processing package may be
    # installed from one site but used by others, so all selected must be
    # current before any runs load-db or npm build).
    _step_pull_all(selected)

    # Step 3 — build/load-db per site (canonical dev → int → prod order)
    if preprocess:
        click.secho("\n[3a/5] Running preprocess.py on selected sites", bold=True)
        for inst in selected:
            _step_preprocess_site(
                INSTANCE_PATHS[inst],
                label=INSTANCE_LABELS[inst],
                env_vars=INSTANCE_ENVS[inst],
            )

    click.secho("\n[3/5] Deploying sites on hgwdev", bold=True)
    for inst in selected:
        _step_deploy_site(
            INSTANCE_PATHS[inst],
            label=INSTANCE_LABELS[inst],
            load_db=load_db,
            env_vars=INSTANCE_ENVS[inst],
        )

    # Step 4 — restart web servers BEFORE tests so e2e hits the new build.
    # Default is no restart; the web process auto-detects DB changes via
    # inode/mtime check in web/lib/db.ts, so JS-only deploys need --restart
    # but DB-only deploys do not.
    if restart:
        _step_restart_psygene(selected)
    else:
        click.secho(
            "\n[4/5] Skipping restart (default). The web process auto-detects DB",
            bold=True,
        )
        click.echo("      changes; pass --restart if JS code changed and needs reloading.")

    # Step 5 — run tests against each deployed site (after build/load-db AND
    # restart so the tests see the as-deployed code + DB). Hard-aborts on
    # first failure.
    if run_tests:
        click.secho("\n[5/5] Running test suite on selected sites", bold=True)
        for inst in selected:
            _step_run_tests_site(
                INSTANCE_PATHS[inst],
                label=INSTANCE_LABELS[inst],
                base_url=INSTANCE_E2E_URLS[inst],
                env_vars=INSTANCE_ENVS[inst],
            )

    click.secho("\nDeployment complete!", fg="green", bold=True)
