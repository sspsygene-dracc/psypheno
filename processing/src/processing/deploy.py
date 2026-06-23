"""Deployment automation for SSPsyGene.

Automates the full deployment workflow. The three instances are independent
deploys, not a staging chain — dev is the staging instance for prod (public
datasets land on dev first, then prod); int is a parallel site for embargoed
datasets whose dataset set may be disjoint from prod's. When `--instances`
lists more than one, they're processed in dev→int→prod order for log clarity,
but they don't gate each other.

All steps run on psygene, which has /hive access just like hgwdev and is
also where the systemd-managed web servers live, so the restart step is
local rather than cross-host:
  1. git push (local)
  2. git pull on each selected site (psygene)
  3. Per-site preprocess.py (optional, --preprocess), load-db (optional,
     --load-db), npm install + npm run build (psygene)
  4. Restart web servers on psygene for the deployed instances (optional,
     --restart) — runs BEFORE tests so e2e hits the new build
  5. Run scripts/test.sh all on each deployed site (optional, --run-tests)
"""

from __future__ import annotations

import concurrent.futures
import getpass
import os
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

import click

# ── Server / path configuration ──────────────────────────────────────────────

PSYGENE = "psygene"
GIT_BRANCH = "main"

# psygene isn't reachable directly from off-campus. Always proxy SSH through
# hgwdev so deploys work without each developer having to add
# `Host psygene / ProxyJump hgwdev` to their personal ~/.ssh/config. We use
# the bare hostname `psygene` (resolved on hgwdev's side) so the host key
# matches anyone who already has a `psygene` entry in known_hosts;
# `StrictHostKeyChecking=accept-new` auto-trusts on first contact rather
# than failing with "host key verification failed" in non-interactive mode.
PSYGENE_SSH_HOST = "psygene"
PSYGENE_PROXY_JUMP = "hgwdev"

PROD_PATH = "/hive/groups/SSPsyGene/sspsygene_website"
DEV_PATH = "/hive/groups/SSPsyGene/sspsygene_website_dev"
INT_PATH = "/hive/groups/SSPsyGene/sspsygene_website_int"


def _site_env(path: str) -> dict[str, str]:
    env = {
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
    # Pass SSPSYGENE_RSCRIPT through to the remote so the load-db on psygene
    # uses the same Rscript binary the deployer has chosen locally — avoids
    # the system-R / libgfortran mismatch reported on issue #174.
    rscript = os.environ.get("SSPSYGENE_RSCRIPT")
    if rscript:
        env["SSPSYGENE_RSCRIPT"] = rscript
    return env


PROD_ENV = _site_env(PROD_PATH)
DEV_ENV = _site_env(DEV_PATH)
INT_ENV = _site_env(INT_PATH)

# Display/iteration order when --instances picks multiple. The three sites
# are independent deploys (dev stages prod's public datasets; int is its own
# parallel site for embargoed data, possibly disjoint from prod) — this
# ordering is just for log readability, not a gating chain.
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
# Source conda.sh from whichever common location exists for this user, so
# the deploy works regardless of where they installed miniconda/anaconda.
# Each `source` candidate is tried in order; the first existing one wins.
CONDA_INIT = (
    'for f in "$HOME/opt_rocky9/miniconda3/etc/profile.d/conda.sh"'
    ' "$HOME/miniconda3/etc/profile.d/conda.sh"'
    ' "$HOME/anaconda3/etc/profile.d/conda.sh"'
    ' "/opt/conda/etc/profile.d/conda.sh"'
    '; do [ -f "$f" ] && source "$f" && break; done'
)

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

# Seconds between "still running" pings for a captured (non-streaming) step.
HEARTBEAT_INTERVAL = 15


class _Heartbeat:
    """Emit a periodic "still running" line while a blocking step executes.

    Captured subprocess calls (the non-streaming branch of `_run_local` /
    `_run_ssh`) print nothing between the initial `-> desc` line and the
    command returning, so a slow step — `npm run build`, a big `git pull`,
    a stuck remote — looks indistinguishable from a hang. This spins up a
    daemon thread that prints `... still running (Ns elapsed): <desc>` every
    `HEARTBEAT_INTERVAL` seconds, so the user always sees forward motion and
    a running elapsed time. Steps that already stream their own output
    (load-db, npm install, the test suites) don't use this — their live
    output is the progress signal.
    """

    def __init__(self, desc: str, interval: int = HEARTBEAT_INTERVAL) -> None:
        self._desc = desc
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._start = 0.0

    def _beat(self) -> None:
        # Event.wait returns True only when stopped; on timeout it returns
        # False, which is our cue to print one heartbeat and loop again.
        while not self._stop.wait(self._interval):
            elapsed = int(time.monotonic() - self._start)
            click.echo(f"     ... still running ({elapsed}s elapsed): {self._desc}")

    def __enter__(self) -> "_Heartbeat":
        self._start = time.monotonic()
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=1)


def _run_local(
    cmd: list[str], *, desc: str, timeout: int = LOCAL_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    """Run a local command; raise DeployError on failure."""
    click.echo(f"  -> {desc}")
    try:
        with _Heartbeat(desc):
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
    except subprocess.TimeoutExpired as e:
        raise DeployError(f"Timed out after {timeout}s: {desc}") from e
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise DeployError(f"Failed: {desc}", detail=output)
    return result


def _ssh_command(host: str, *, tty: bool = False) -> list[str]:
    """Build the ssh prefix for *host* (without the remote command).

    For PSYGENE we always inject `-J hgwdev` and `accept-new` host-key
    handling, so deploys succeed without per-user ~/.ssh/config entries
    for `psygene` and without an interactive host-key prompt on first run.

    We also force agent forwarding (`-A`) to psygene. The git remote on the
    server checkouts is `git@github.com:…` (SSH), so the `git pull` step
    authenticates to GitHub *from psygene* — which needs a GitHub-authorized
    key there. Without `-A`, the only ways that worked were a per-user key
    sitting in `~/.ssh` on psygene or a per-user `Host psygene → ForwardAgent
    yes` config block — neither of which the "you don't need a psygene config
    block" deploy design gives wranglers, so their pull failed with
    `Permission denied (publickey)`. `-A` forwards the deployer's *laptop*
    agent (the same one they push from) all the way to psygene, so the pull
    authenticates with no server-side setup. (Forwarding to the final hop of a
    `-J` jump requires `-A` on the command line; a ForwardAgent setting for the
    jump host alone does not reach psygene.)
    """
    cmd = ["ssh"]
    if tty:
        cmd.append("-t")
    if host == PSYGENE:
        cmd.extend(
            [
                "-A",
                "-o", "StrictHostKeyChecking=accept-new",
                "-J", PSYGENE_PROXY_JUMP,
                PSYGENE_SSH_HOST,
            ]
        )
    else:
        cmd.append(host)
    return cmd


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
                [*_ssh_command(host, tty=True), remote_cmd],
                timeout=timeout,
            )
            result = subprocess.CompletedProcess(
                proc.args, proc.returncode, stdout="", stderr=""
            )
        else:
            with _Heartbeat(f"[{host}] {desc}"):
                result = subprocess.run(
                    [*_ssh_command(host), remote_cmd],
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

    # Uncommitted changes to TRACKED files? Untracked files (--untracked-files=no
    # excludes them) are harmless to a deploy — only modifications/staging/
    # deletions of tracked files should block, since those are what a deploy's
    # git pull would conflict with.
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise DeployError(
            "Working directory has uncommitted changes to tracked files — "
            "commit or stash before deploying.",
            detail=result.stdout.strip(),
        )
    click.echo("  -> Tracked files are clean (untracked files ignored)")

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

    The pull is wrapped with `safe.directory='*'` so wranglers don't need
    a per-user `git config --add safe.directory ...` for the server
    checkout paths (they're owned by whoever deployed first, which trips
    git's CVE-2022-24765 mitigation otherwise).

    After the pull we run a backstop chmod over files the deploying user
    owns, to keep the shared checkout group-writable for the next
    deployer. The repo's `.githooks/post-merge` already does this for
    `git pull`, but we belt-and-suspenders it here so a deploy that hits
    a checkout missing the hook config still self-heals.

    The pull and the chmod sweep are run as **two separate SSH steps** with
    their own heartbeats, rather than one compound command. Previously they
    were fused under a single `git pull (...)` heartbeat, which made a slow
    chmod look like a slow pull — confusing, because the pull is near-instant
    and it was the *sweep* eating the wall time. Keeping them separate also
    lets the pull fail the deploy (check=True) while the sweep stays
    best-effort (check=False).

    The sweep is scoped to source + data and **prunes the npm dependency /
    build trees** (`node_modules`, `.next`) plus `.git`. Those are gitignored,
    don't need to be group-writable for the next deployer, and — at tens of
    thousands of files — were the entire reason the sweep took ~a minute. The
    cost was never `chmod` itself (it's batched via `-exec … +`); it was the
    `find` tree-walk + per-file `stat` over `node_modules`. A plain
    `chmod -R g+w` would have been just as slow for the same reason. Pruning
    those dirs cuts the file count ~99% and the sweep drops to a few seconds.
    Everything left — `data/` and its (gitignored) payloads, and all tracked
    source — is what actually needs to stay group-writable.
    """
    click.secho("\n[2/5] Pulling latest code on psygene", bold=True)
    for inst in instances:
        path = INSTANCE_PATHS[inst]
        # Step one: the pull itself. check=True (the default) so a failed pull
        # fails the deploy — we must not build/load-db on stale code.
        _run_ssh(
            PSYGENE,
            f"cd {path} && git -c safe.directory='*' pull",
            desc=f"git pull ({path})",
        )
        # Step two: best-effort group-write backstop, scoped to source + data
        # and pruning the npm dep/build trees (the slow, unimportant part).
        # check=False so a chmod hiccup (files owned by another wrangler, etc.)
        # never fails the deploy.
        _run_ssh(
            PSYGENE,
            f"cd {path} && "
            f"find . \\( -name node_modules -o -name .next -o -name .git \\) "
            f"-prune -o -user \"$(id -un)\" ! -perm -g+w "
            f"\\( -type d -exec chmod g+ws {{}} + "
            f"-o -type f -exec chmod g+w {{}} + \\) 2>/dev/null; true",
            desc=f"group-write backstop ({path})",
            check=False,
        )


PREPROCESS_MAX_WORKERS = 8


# Patterns that mean "preprocess.py died because a Python package isn't
# installed in the sspsygene conda env", in priority order. The capture group
# is the missing package name. pandas' "Missing optional dependency" is the
# common one (it's what xlrd/openpyxl/etc. surface as); the bare ImportError /
# ModuleNotFoundError forms cover everything else. #204.
_MISSING_DEP_PATTERNS = (
    re.compile(r"Missing optional dependency ['\"]([\w.\-]+)['\"]"),
    re.compile(r"ModuleNotFoundError: No module named ['\"]([\w.\-]+)['\"]"),
    re.compile(r"ImportError: No module named ['\"]?([\w.\-]+)['\"]?"),
)


def _detect_missing_dependency(output: str) -> str | None:
    """Return the missing package name if `output` looks like a preprocess.py
    failure caused by an uninstalled dependency, else None. Used to turn a raw
    pandas/import traceback into an actionable "install X into the env" hint."""
    for pattern in _MISSING_DEP_PATTERNS:
        match = pattern.search(output)
        if match:
            return match.group(1)
    return None


def _step_preprocess_site(
    path: str,
    *,
    label: str,
    env_vars: dict[str, str],
) -> None:
    """Run every dataset's preprocess.py in parallel under the conda env.

    Each dataset gets its own ssh + `conda run python preprocess.py`
    invocation, dispatched through a ThreadPoolExecutor (PREPROCESS_MAX_WORKERS
    concurrent jobs). Each job logs a `START` line when it begins and an
    `OK`/`FAIL` line (with a running done/total count) when it finishes; its
    captured stdout/stderr is printed on completion, prefixed with the
    dataset name. A background heartbeat lists which datasets are still in
    flight (and for how long) every HEARTBEAT_INTERVAL seconds, so a slow or
    stuck dataset is visible immediately instead of looking like a hang.
    Waits for all in-flight jobs to finish before raising, so the user sees
    every failure rather than only the first one to hit.
    """
    click.echo(f"\n  --- {label} preprocess ({path}) ---")

    list_result = _run_ssh(
        PSYGENE,
        f"cd {path} && find data/datasets -mindepth 2 -maxdepth 2 "
        f"-name preprocess.py -printf '%h\\n' | sort",
        desc="Listing datasets with preprocess.py",
    )
    dataset_dirs = [d for d in list_result.stdout.strip().splitlines() if d]
    if not dataset_dirs:
        click.echo("  No datasets with preprocess.py — skipping.")
        return

    env_prefix = " ".join(f"{k}={v}" for k, v in env_vars.items()) + " "
    workers = min(PREPROCESS_MAX_WORKERS, len(dataset_dirs))
    click.echo(
        f"  Running preprocess.py for {len(dataset_dirs)} dataset(s) "
        f"with {workers} parallel workers..."
    )

    total = len(dataset_dirs)
    # in_flight maps a currently-running dataset name -> its start time, so the
    # heartbeat can report which jobs are live and for how long. `completed`
    # is the running done count. Both are touched from worker threads, the
    # heartbeat thread, and the main loop, so guard them with `lock`.
    in_flight: dict[str, float] = {}
    completed = 0
    lock = threading.Lock()

    def run_one(dataset_dir: str) -> tuple[str, int, str]:
        name = dataset_dir.removeprefix("data/datasets/")
        with lock:
            in_flight[name] = time.monotonic()
        click.echo(f"  START [preprocess] {name}")
        inner = f"cd {shlex.quote(dataset_dir)} && python preprocess.py"
        cmd = (
            f"cd {path} && {CONDA_INIT} && "
            f"{env_prefix}conda run --no-capture-output -n {CONDA_ENV} "
            f"bash -c {shlex.quote(inner)}"
        )
        try:
            proc = subprocess.run(
                [*_ssh_command(PSYGENE), cmd],
                capture_output=True,
                text=True,
                timeout=PREPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return dataset_dir, -1, f"Timed out after {PREPROCESS_TIMEOUT}s"
        finally:
            with lock:
                in_flight.pop(name, None)
        output = (proc.stdout or "") + (proc.stderr or "")
        return dataset_dir, proc.returncode, output

    stop_beat = threading.Event()

    def heartbeat() -> None:
        while not stop_beat.wait(HEARTBEAT_INTERVAL):
            with lock:
                snapshot = sorted(
                    (time.monotonic() - started, n)
                    for n, started in in_flight.items()
                )
                done = completed
            if snapshot:
                running = ", ".join(f"{n} ({int(e)}s)" for e, n in snapshot)
                click.echo(
                    f"     ... preprocess {done}/{total} done; "
                    f"{len(snapshot)} in flight: {running}"
                )

    beat = threading.Thread(target=heartbeat, daemon=True)
    beat.start()

    failures: list[str] = []
    # dataset name -> missing package, for the actionable summary at the end.
    missing_deps: dict[str, str] = {}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run_one, d) for d in dataset_dirs]
            for future in concurrent.futures.as_completed(futures):
                dataset_dir, rc, output = future.result()
                name = dataset_dir.removeprefix("data/datasets/")
                with lock:
                    completed += 1
                    done = completed
                if rc == 0:
                    click.echo(f"  OK   [preprocess] {name} ({done}/{total})")
                else:
                    click.secho(
                        f"  FAIL [preprocess] {name} (exit {rc}) ({done}/{total})",
                        fg="red",
                    )
                    missing = _detect_missing_dependency(output)
                    if missing:
                        # Surface an actionable hint above the raw traceback so
                        # the wrangler doesn't have to decode a pandas error
                        # to know what to install (#204).
                        missing_deps[name] = missing
                        click.secho(
                            f"    -> missing dependency '{missing}' — install "
                            f"it into the {CONDA_ENV} conda env "
                            f"(conda run -n {CONDA_ENV} pip install {missing}), "
                            f"and consider adding it to processing/pyproject.toml.",
                            fg="yellow",
                        )
                    for line in output.strip().splitlines():
                        click.echo(f"    | {line}")
                    failures.append(name)
    finally:
        stop_beat.set()
        beat.join(timeout=1)

    if failures:
        if missing_deps:
            # Group the missing-dependency failures into one install line so the
            # operator can fix them all at once before re-running the deploy.
            pkgs = " ".join(sorted(set(missing_deps.values())))
            affected = ", ".join(
                f"{name} ({pkg})" for name, pkg in sorted(missing_deps.items())
            )
            click.secho(
                f"\n  {len(missing_deps)} dataset(s) failed on a missing "
                f"Python dependency: {affected}.\n"
                f"  Install into the {CONDA_ENV} env, then re-deploy:\n"
                f"      conda run -n {CONDA_ENV} pip install {pkgs}",
                fg="yellow",
            )
        raise DeployError(
            f"{len(failures)}/{len(dataset_dirs)} preprocess job(s) failed: "
            + ", ".join(failures)
        )


def _step_run_tests_site(
    path: str,
    *,
    label: str,
    base_url: str,
    env_vars: dict[str, str],
) -> None:
    """Run scripts/test.sh server on the deployed site (via ssh), then
    scripts/test.sh e2e locally against base_url. Splits like this because
    psygene doesn't have playwright browsers and `npx playwright install`
    needs system deps that aren't there — so e2e has to run from a
    developer laptop, where web/node_modules already has playwright +
    its browsers. Aborts on first failure (raises DeployError)."""
    click.echo(f"\n  --- {label} tests ({path}) ---")

    # 1. Server-side suites on psygene (python + web-tsc + web-unit + data-corr).
    test_env = {
        **env_vars,
        "SSPSYGENE_TEST_HOMOLOGY_DIR": f"{path}/data/homology",
    }
    env_prefix = " ".join(f"{k}={v}" for k, v in test_env.items()) + " "
    inner = (
        "set -e; "
        # Hand scripts/test.sh the conda env's pytest — the local default of
        # processing/.venv-claude/bin/pytest doesn't exist on psygene.
        'PYTEST="$(command -v pytest)" '
        f"{env_prefix}"
        "scripts/test.sh server"
    )
    cmd = (
        f"cd {path} && {CONDA_INIT} && "
        f"conda run --no-capture-output -n {CONDA_ENV} bash -c {shlex.quote(inner)}"
    )
    _run_ssh(
        PSYGENE,
        cmd,
        desc="Running scripts/test.sh server (python + web + data-corr)",
        timeout=TEST_TIMEOUT,
        stream=True,
    )

    # 2. e2e suite locally against base_url. Playwright drives browsers from
    # the laptop's web/node_modules; the deployed Next.js server only
    # serves HTTP requests.
    repo_root = Path(__file__).resolve().parents[3]
    test_sh = repo_root / "scripts" / "test.sh"
    if not test_sh.is_file():
        raise DeployError(f"scripts/test.sh not found at {test_sh}")
    click.echo(
        f"  -> Running scripts/test.sh e2e locally against {base_url}"
    )
    e2e_env = {**os.environ, "E2E_BASE_URL": base_url}
    try:
        proc = subprocess.run(
            [str(test_sh), "e2e"], env=e2e_env, timeout=TEST_TIMEOUT
        )
    except subprocess.TimeoutExpired as e:
        raise DeployError(
            f"e2e tests timed out after {TEST_TIMEOUT}s against {base_url}"
        ) from e
    if proc.returncode != 0:
        raise DeployError(
            f"e2e tests failed (exit {proc.returncode}) against {base_url}"
        )


def _step_deploy_site(
    path: str,
    *,
    label: str,
    load_db: bool,
    build: bool,
    env_vars: dict[str, str] | None = None,
) -> None:
    """Optionally rebuild DB, and optionally build the web app on psygene.

    `build` is off by default because (a) wranglers running data deploys
    don't need it, and (b) the resulting service restart only works
    cleanly for the user who owns the systemd unit (see restart step).
    """
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

    if not build:
        click.echo(
            "  Skipping npm install + npm run build (default — pass --build "
            "when web/ code has changed)."
        )
        return

    # Sync npm deps from package-lock.json before building so a package.json
    # bump in the just-pulled commit doesn't get built against a stale
    # node_modules.
    _run_ssh(
        PSYGENE,
        f"cd {path}/web && npm install",
        desc="npm install",
        timeout=BUILD_TIMEOUT,
        stream=True,
    )

    # Stream the build (like npm install above) so its per-route compilation
    # progress is visible live rather than buffered until the build finishes
    # — a captured build is a multi-minute silent black box.
    _run_ssh(
        PSYGENE,
        f"cd {path}/web && npm run build",
        desc="npm run build (this may take a few minutes)",
        timeout=BUILD_TIMEOUT,
        stream=True,
    )


def _step_meta_analysis_site(
    path: str,
    *,
    label: str,
    no_r_cache: bool = False,
    env_vars: dict[str, str] | None = None,
) -> None:
    """Run `sspsygene meta-analysis` on one psygene site.

    Reads that site's already-built sspsygene.db and writes its sibling
    sspsygene-meta.db via atomic swap (issue #176). No build / restart needed:
    the web process auto-detects the new meta DB file the same way it detects a
    rebuilt sspsygene.db (web/lib/db.ts re-stats both files). Multi-user-safe —
    it only creates/replaces the meta DB file under the deployer's account (no
    systemd / kill interaction), so unlike the restart step it works the same
    for any wrangler in the protein group."""
    click.echo(f"\n  --- meta-analysis: {label} ({path}) ---")
    env_prefix = ""
    if env_vars:
        env_prefix = " ".join(f"{k}={v}" for k, v in env_vars.items()) + " "
    flags = " --no-r-cache" if no_r_cache else ""
    cmd = (
        f"cd {path} && "
        f"{CONDA_INIT} && "
        f"{env_prefix}conda run --no-capture-output -n {CONDA_ENV} "
        f"sspsygene meta-analysis{flags}"
    )
    _run_ssh(
        PSYGENE,
        cmd,
        desc="sspsygene meta-analysis (this may take a while)",
        timeout=LOAD_DB_TIMEOUT,
        stream=True,
    )


def run_deploy_meta_analysis(
    *,
    no_push: bool = False,
    instances: str | None = None,
    no_r_cache: bool = False,
) -> None:
    """Refresh sspsygene-meta.db on the selected psygene sites (issue #176).

    The meta chain is independent of the dataset/deploy chain: it pushes +
    pulls code (so the server runs the current meta-analysis logic), then runs
    `sspsygene meta-analysis` on each selected site against that site's existing
    sspsygene.db. It does NOT rebuild datasets, build the web app, or restart
    services. The maintainer invokes this on their own cadence, e.g. after a
    batch of dataset additions has settled."""
    selected = _resolve_instances(instances)
    _preflight_checks()

    if no_push:
        click.secho("\n[1/3] Skipping git push (--no-push)", bold=True)
    else:
        _step_push()

    _step_pull_all(selected)

    click.secho("\n[3/3] Running meta-analysis on selected sites", bold=True)
    for inst in selected:
        _step_meta_analysis_site(
            INSTANCE_PATHS[inst],
            label=INSTANCE_LABELS[inst],
            no_r_cache=no_r_cache,
            env_vars=INSTANCE_ENVS[inst],
        )

    click.secho("\nMeta-analysis deployment complete!", fg="green", bold=True)


def _step_restart_psygene(instances: list[str]) -> None:
    """Restart Next.js processes on psygene for the given instances.

    Kills the `npm start --port NNNN` parents matching each instance's port;
    systemd respawns the unit (which terminates the next-server child along
    with it). Then waits for each instance's public URL to respond before
    returning, so subsequent steps (e.g. e2e tests) don't race the restart.
    """
    ports = [INSTANCE_PORTS[i] for i in instances]
    labels = ", ".join(INSTANCE_LABELS[i] for i in instances)
    click.secho(f"\n[4/5] Restarting web servers on psygene ({labels})", bold=True)

    port_alts = "|".join(str(p) for p in ports)
    grep_cmd = (
        'ps -fu "$USER" | '
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


# ── Standalone restart (run directly on psygene) ─────────────────────────────


def _find_npm_pids_local(ports: list[int]) -> list[tuple[str, str]]:
    """Return (pid, full ps line) for `npm start --port P` processes owned by
    the current user, for any P in *ports*.

    Mirrors the grep the SSH-based restart step uses, but runs `ps` locally
    (no SSH) and filters in Python so a `grep`-finds-nothing exit code isn't
    mistaken for an error. `ps -fu` scopes to the current user, so a process
    owned by another user (e.g. the systemd unit's User=jbirgmei) won't show
    up — which is exactly why a non-owner's kill no-ops.
    """
    user = getpass.getuser()
    result = subprocess.run(["ps", "-fu", user], capture_output=True, text=True)
    pattern = re.compile(
        r"npm start --port (?:" + "|".join(str(p) for p in ports) + r")\b"
    )
    matches: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not pattern.search(line):
            continue
        # `ps -f` columns: UID PID PPID C STIME TTY TIME CMD — PID is field 2.
        parts = line.split()
        if len(parts) >= 2:
            matches.append((parts[1], line.strip()))
    return matches


def _wait_for_local_service(port: int, label: str, timeout: int = 60) -> None:
    """Poll localhost:PORT until the instance answers (or *timeout* elapses).

    Probes the local Next.js server directly rather than the public URL, so
    the check reflects the actual respawned process on this box, independent
    of Apache's reverse proxy / off-campus DNS.
    """
    url = f"http://localhost:{port}/api/full-datasets"
    click.echo(f"  Waiting for {label} ({url}) to respond...")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        probe = subprocess.run(
            ["curl", "-fsS", "--max-time", "5", url],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            click.echo(f"    -> {label} is up.")
            return
        time.sleep(2)
    raise DeployError(
        f"Timed out after {timeout}s waiting for {label} to respond at {url}"
    )


def run_restart(instances: list[str]) -> None:
    """Restart Next.js web servers locally on psygene by killing their
    `npm start --port NNNN` parent; systemd respawns the unit (which also
    terminates the next-server child).

    Unlike _step_restart_psygene (which drives the kill over SSH from a
    developer laptop as part of a deploy), this is meant to be run *directly
    on psygene*: it greps the local process table, kills the matching PIDs,
    and waits for each service to answer on localhost:PORT again.

    Multi-user caveat: `kill` only signals processes you own, and the systemd
    units run as User=jbirgmei, so this only actually bounces a service when
    run by jbirgmei. For another user it finds no matching processes (they're
    owned by jbirgmei) and no-ops with a warning — ask Johannes, or
    `sudo systemctl restart sspsygene{,-dev,-int}` if you have sudo.
    """
    labels = ", ".join(INSTANCE_LABELS[i] for i in instances)
    ports = [INSTANCE_PORTS[i] for i in instances]
    click.secho(f"Restarting web servers on psygene ({labels})", bold=True)

    matches = _find_npm_pids_local(ports)
    if not matches:
        click.secho(
            f"  No npm processes found for {labels} owned by "
            f"{getpass.getuser()} — nothing to kill.\n"
            "  (The systemd units run as jbirgmei, so `kill` only finds them "
            "when you run this AS jbirgmei. As another user this is expected; "
            "ask Johannes or use `sudo systemctl restart sspsygene{,-dev,-int}`.)",
            fg="yellow",
        )
    else:
        click.echo(f"  Found {len(matches)} process(es):")
        for _, line in matches:
            click.echo(f"    {line}")
        pids = [pid for pid, _ in matches]
        _run_local(["kill", *pids], desc=f"Killing {len(pids)} process(es)")
        click.echo("  Processes killed — systemd should restart them automatically.")

    for inst in instances:
        _wait_for_local_service(INSTANCE_PORTS[inst], INSTANCE_LABELS[inst])

    click.secho("\nRestart complete!", fg="green", bold=True)


# ── Promote dev → prod (copy built DBs, no rebuild) ──────────────────────────
#
# dev and prod live on the same /hive filesystem (both reachable from psygene
# and hgwdev), so "promote" is a local `cp` of dev's already-built SQLite
# file(s) into prod's db dir followed by an atomic `mv` swap — never a
# cross-host rsync or a rebuild on prod. The web process re-opens its read-only
# handle when the file inode changes (web/lib/db.ts re-stats sspsygene.db and
# sspsygene-meta.db), exactly as it does after `load-db` / `meta-analysis`, so
# no service restart is needed — which makes this multi-user-safe (no
# systemd/kill interaction, unlike `deploy --restart`).
#
# Direction is asymmetric on purpose (issue #178): only dev → prod. There is no
# copy-from-prod (no reason to overwrite dev with prod's older build) and int is
# never a source or target (it carries its own, possibly-embargoed dataset set).

DB_FILENAME = "sspsygene.db"
META_DB_FILENAME = "sspsygene-meta.db"


def _db_file(site_path: str, filename: str) -> str:
    return f"{site_path}/data/db/{filename}"


def _on_hive_host() -> bool:
    """True when dev and prod's /hive trees are visible as local directories.

    This is what distinguishes a developer laptop (paths absent → must SSH)
    from psygene/hgwdev (paths present → run the copy locally)."""
    return Path(DEV_PATH).is_dir() and Path(PROD_PATH).is_dir()


def _resolve_promote_local(local: bool | None) -> bool:
    """Decide whether to run the promote copy locally or over SSH.

    `local=None` auto-detects via `_on_hive_host()`; an explicit `local=True`
    off a /hive host is a hard error (the local `cp` would have nothing to copy).
    """
    if local is None:
        local = _on_hive_host()
    if local and not _on_hive_host():
        raise DeployError(
            "--local was requested but this host can't see the /hive trees "
            f"({DEV_PATH} is not a local directory). Run promote-dev-to-prod "
            "directly on hgwdev or psygene, or drop --local to SSH in from a "
            "laptop."
        )
    return local


def _run_promote(
    local: bool,
    shell_cmd: str,
    *,
    desc: str,
    timeout: int = SSH_TIMEOUT,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a promote shell command on psygene/hgwdev — locally or over SSH.

    The promote path is the one place that still needs the laptop-vs-server
    duality the old `_Transport` gave `deploy` (issue #178: "run on a laptop
    or on hgwdev/psygene"). `deploy` itself is SSH-only again, so rather than
    resurrect the whole transport abstraction we keep one tiny dispatcher: SSH
    delegates to `_run_ssh`; local runs `bash -c` and captures output with the
    same `check` semantics, so a smoke check like `test -f` can tolerate a
    non-zero exit.
    """
    if not local:
        return _run_ssh(PSYGENE, shell_cmd, desc=desc, timeout=timeout, check=check)
    click.echo(f"  -> [psygene-local] {desc}")
    try:
        result = subprocess.run(
            ["bash", "-c", shell_cmd], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        raise DeployError(
            f"Timed out after {timeout}s on psygene-local: {desc}"
        ) from e
    if check and result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise DeployError(f"Failed on psygene-local: {desc}", detail=output)
    return result


def _sqlite_scalar(
    local: bool,
    db_path: str,
    query: str,
    *,
    desc: str,
    check: bool = True,
) -> int | None:
    """Run a scalar SELECT against *db_path* read-only and return the int.

    Uses the stdlib `sqlite3` via `python3 -c` rather than the `sqlite3` CLI
    (not guaranteed on a bare psygene PATH; python3 + its bundled sqlite3 are).
    Opens the file in read-only URI mode so a smoke check never perturbs a DB
    that's being served. Returns None when `check=False` and the query fails
    (e.g. file missing / table absent), so callers can treat that as "unknown".
    """
    code = (
        "import sqlite3;"
        f"c=sqlite3.connect('file:{db_path}?mode=ro',uri=True);"
        f"print(c.execute({query!r}).fetchone()[0])"
    )
    cmd = f"python3 -c {shlex.quote(code)}"
    result = _run_promote(local, cmd, desc=desc, check=check)
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except (ValueError, AttributeError):
        return None


def _assert_source_db(
    local: bool, db_path: str, *, label: str, min_data_tables: int
) -> int:
    """Refuse to promote unless dev's *db_path* exists and looks sane.

    Returns the `data_tables` row count so the caller can verify prod matches
    it after the swap. Hard-fails (DeployError) if the file is missing or the
    smoke count is below `min_data_tables`.
    """
    exists = _run_promote(
        local,
        f"test -f {shlex.quote(db_path)}",
        desc=f"Checking {label} exists ({db_path})",
        check=False,
    )
    if exists.returncode != 0:
        raise DeployError(
            f"Source {label} not found on dev at {db_path}. Build it on dev "
            "first (`sspsygene deploy --load-db --instances dev`)."
        )
    count = _sqlite_scalar(
        local,
        db_path,
        "SELECT count(*) FROM data_tables",
        desc=f"Smoke-checking {label} (data_tables row count)",
    )
    if count is None or count < min_data_tables:
        raise DeployError(
            f"Source {label} smoke check failed: data_tables has "
            f"{count if count is not None else 'an unreadable number of'} "
            f"row(s), need at least {min_data_tables}. Refusing to promote a "
            "stale/empty build to prod."
        )
    click.echo(f"  -> {label}: {count} data_tables row(s) — OK")
    return count


def run_promote_dev_to_prod(
    *,
    include_meta_analysis: bool = True,
    local: bool | None = None,
    dry_run: bool = False,
    min_data_tables: int = 1,
) -> None:
    """Copy dev's built SQLite DB file(s) into prod and atomically swap them in.

    Promotes a *verified* dev build to prod without re-running preprocess /
    load-db on prod — dev becomes the source-of-truth build server, so prod
    serves byte-identical bytes (issue #178). Copies the main dataset DB
    (`sspsygene.db`) and, by default, the meta-analysis DB (`sspsygene-meta.db`)
    when dev has one; pass `include_meta_analysis=False` to copy only the main
    DB. Both files are copied into prod's db dir as `.new` siblings first, then
    renamed back-to-back, minimising the window where prod's main and meta DBs
    disagree. No restart: the web app re-opens on inode change.

    `local=None` auto-detects whether to run the copy locally (on hgwdev/psygene)
    or over SSH (from a laptop). int is never involved — neither source nor
    target.
    """
    local = _resolve_promote_local(local)
    where = "locally" if local else "over SSH (proxy-jump hgwdev)"
    click.secho(
        f"Promote dev → prod (copy built DB file{'s' if include_meta_analysis else ''}, "
        f"running {where})",
        bold=True,
    )

    src_main = _db_file(DEV_PATH, DB_FILENAME)
    dst_main = _db_file(PROD_PATH, DB_FILENAME)
    src_meta = _db_file(DEV_PATH, META_DB_FILENAME)
    dst_meta = _db_file(PROD_PATH, META_DB_FILENAME)

    # ── 1. Sanity-check the source(s) on dev ─────────────────────────────────
    click.secho("\n[1/3] Checking dev source build", bold=True)
    dev_main_count = _assert_source_db(
        local, src_main, label="main DB", min_data_tables=min_data_tables
    )

    copy_meta = include_meta_analysis
    if include_meta_analysis:
        meta_exists = _run_promote(
            local,
            f"test -f {shlex.quote(src_meta)}",
            desc=f"Checking meta DB exists ({src_meta})",
            check=False,
        )
        if meta_exists.returncode != 0:
            click.secho(
                "  No meta-analysis DB on dev — skipping the meta copy. Prod's "
                "existing meta DB (if any) is left untouched; it may now be "
                "stale relative to the promoted main DB. Run `sspsygene "
                "deploy-meta-analysis --instances dev` then re-promote to "
                "refresh it.",
                fg="yellow",
            )
            copy_meta = False

    # ── 2. Copy into prod and atomically swap ────────────────────────────────
    click.secho("\n[2/3] Copying into prod and swapping", bold=True)
    pairs = [(src_main, dst_main, "main DB")]
    if copy_meta:
        pairs.append((src_meta, dst_meta, "meta DB"))

    if dry_run:
        for src, dst, lbl in pairs:
            click.echo(f"  [dry-run] would copy {lbl}: {src} -> {dst} (atomic swap)")
        click.secho("\n[dry-run] No files were modified.", fg="yellow", bold=True)
        return

    # Copy every file to a `.new` sibling first, then rename them all — so the
    # two DBs flip in quick succession rather than leaving a long window where
    # prod's main DB is new but its meta DB is still old.
    copy_lines = "\n".join(
        f"cp -f {shlex.quote(src)} {shlex.quote(dst + '.new')}\n"
        # Keep the staged file group-writable so the next wrangler to promote
        # (a different protein-group user) can overwrite it. Best-effort: only
        # works on files we own, hence `|| true`.
        f"chmod g+w {shlex.quote(dst + '.new')} 2>/dev/null || true"
        for src, dst, _ in pairs
    )
    swap_lines = "\n".join(
        f"mv -f {shlex.quote(dst + '.new')} {shlex.quote(dst)}" for _, dst, _ in pairs
    )
    _run_promote(
        local,
        "set -e\n" + copy_lines + "\n" + swap_lines,
        desc="cp dev DB(s) → prod .new, then atomic mv swap",
        timeout=LOAD_DB_TIMEOUT,
    )
    for _, _, lbl in pairs:
        click.echo(f"  -> swapped {lbl} into prod")

    # ── 3. Verify prod now serves the promoted bytes ─────────────────────────
    click.secho("\n[3/3] Verifying prod", bold=True)
    prod_main_count = _sqlite_scalar(
        local,
        dst_main,
        "SELECT count(*) FROM data_tables",
        desc="Re-reading prod main DB (data_tables row count)",
    )
    if prod_main_count != dev_main_count:
        raise DeployError(
            f"Post-swap check failed: prod main DB has {prod_main_count} "
            f"data_tables row(s) but dev had {dev_main_count}. The copy may "
            "not have landed — inspect prod's data/db/ manually."
        )
    click.echo(
        f"  -> prod main DB matches dev ({prod_main_count} data_tables rows)."
    )
    if copy_meta:
        prod_meta_groups = _sqlite_scalar(
            local,
            dst_meta,
            "SELECT count(*) FROM combined_pvalue_groups",
            desc="Re-reading prod meta DB (combined_pvalue_groups)",
            check=False,
        )
        click.echo(
            f"  -> prod meta DB present "
            f"({prod_meta_groups if prod_meta_groups is not None else '?'} "
            "combined_pvalue_groups)."
        )

    click.secho(
        "\nPromotion complete! Prod now serves dev's build. The web process "
        "picks up the new DB inode on its next request — no restart needed.",
        fg="green",
        bold=True,
    )


# ── Main entry point ────────────────────────────────────────────────────────


def _resolve_instances(instances: str | None) -> list[str]:
    """Parse the --instances string and return the requested instances in INSTANCE_ORDER.

    Accepts None (= all three) or a comma-separated subset. Unknown tokens raise
    ClickException; duplicates are deduped silently. The returned order is the
    iteration order — the instances are independent deploys, not a promotion chain.
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


def _run_build_pipeline(
    selected: list[str],
    *,
    load_db: bool,
    build: bool,
    restart: bool,
    preprocess: bool,
    run_tests: bool,
    include_meta_analysis: bool = False,
) -> None:
    """Steps 2–5 of a deploy (pull → preprocess/load-db/build → restart →
    tests) on the selected psygene sites.

    Step 1 (git push) and the preflight checks live in `run_deploy` — they're
    laptop-only — so this helper is just the server-side build pipeline.
    """
    # Step 2 — git pull selected sites first (the processing package may be
    # installed from one site but used by others, so all selected must be
    # current before any runs load-db or npm build).
    _step_pull_all(selected)

    # Step 3 — build/load-db per site (iterated in INSTANCE_ORDER for log clarity)
    if preprocess:
        click.secho("\n[3a/5] Running preprocess.py on selected sites", bold=True)
        for inst in selected:
            _step_preprocess_site(
                INSTANCE_PATHS[inst],
                label=INSTANCE_LABELS[inst],
                env_vars=INSTANCE_ENVS[inst],
            )

    click.secho("\n[3/5] Deploying sites on psygene", bold=True)
    for inst in selected:
        _step_deploy_site(
            INSTANCE_PATHS[inst],
            label=INSTANCE_LABELS[inst],
            load_db=load_db,
            build=build,
            env_vars=INSTANCE_ENVS[inst],
        )

    # Step 3c — optional convenience: refresh the separate meta DB on the same
    # sites (issue #176). Off by default; equivalent to following this deploy
    # with `sspsygene deploy-meta-analysis` on the same instances. Runs after
    # load-db so it reads the freshly-built datasets.
    if include_meta_analysis:
        click.secho(
            "\n[3c/5] Refreshing meta-analysis on selected sites "
            "(--include-meta-analysis)",
            bold=True,
        )
        for inst in selected:
            _step_meta_analysis_site(
                INSTANCE_PATHS[inst],
                label=INSTANCE_LABELS[inst],
                env_vars=INSTANCE_ENVS[inst],
            )

    # Step 4 — restart web servers BEFORE tests so e2e hits the new build.
    # Default tracks --build: a build mints a new Next.js build ID that
    # invalidates the running service's served HTML (references to the old
    # build ID's manifest files 404 because the new build overwrote them on
    # disk), so any --build run also needs a restart. Data-only deploys
    # (--load-db / --preprocess) don't, since the web process auto-detects
    # DB inode/mtime changes via web/lib/db.ts.
    if restart:
        _step_restart_psygene(selected)
    elif build:
        click.secho(
            "\n[4/5] Skipping restart (--no-restart) AFTER --build. Heads up: ",
            bold=True,
        )
        click.echo(
            "      `npm run build` invalidated the running service's served HTML;"
        )
        click.echo(
            "      users may hit 404s on `_buildManifest.js` until you restart."
        )
    else:
        click.secho(
            "\n[4/5] Skipping restart (default for data-only deploys).",
            bold=True,
        )

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


def _confirm_prod_db_rebuild(
    selected: list[str],
    *,
    load_db: bool,
    preprocess: bool,
) -> None:
    """Warn + confirm before rebuilding the DB directly on prod.

    Rebuilding prod's DB in place (`--load-db` / `--preprocess` against prod)
    is the thing `promote-dev-to-prod` exists to replace (issue #178): it
    re-runs preprocess/load-db on prod independently of dev, which risks
    serving different bytes than the verified dev build (gitignored-payload
    skew, tool/version drift). The standard path is to promote dev's
    already-built DB instead. Only fires when prod is actually a data-rebuild
    target — a code-only deploy (`--build`, no DB rebuild) isn't covered by
    promote and is left alone.
    """
    if "prod" not in selected or not (load_db or preprocess):
        return
    click.secho(
        "\nWARNING: this will rebuild the database directly on PRODUCTION.",
        fg="yellow",
        bold=True,
    )
    click.echo(
        "  The standard way to update prod is to promote a verified dev build\n"
        "  rather than re-running preprocess/load-db on prod. Promoting copies\n"
        "  dev's already-built DB so prod serves byte-identical bytes (no drift\n"
        "  from gitignored-payload skew or tool/version differences); it's\n"
        "  faster and multi-user-safe (no restart). See issue #178.\n"
        "\n"
        "  Standard path:  sspsygene promote-dev-to-prod\n"
    )
    if not click.confirm("  Rebuild on prod directly anyway?"):
        click.secho("  Aborted — use the promote path above instead.", fg="yellow")
        raise SystemExit(0)


def run_deploy(
    *,
    load_db: bool = False,
    no_push: bool = False,
    instances: str | None = None,
    build: bool = False,
    restart: bool | None = None,
    preprocess: bool = False,
    run_tests: bool = False,
    include_meta_analysis: bool = False,
) -> None:
    """Run the full deployment pipeline from a laptop (SSHes into psygene).

    `build` gates `npm install` + `npm run build` (default off — wranglers
    running data deploys never need it). When `build` is true, `restart`
    defaults to true because the new build mints a fresh Next.js build ID
    that invalidates the running service's served HTML; pass `restart=False`
    explicitly to opt out. `include_meta_analysis` additionally refreshes the
    separate meta DB on each site (off by default; issue #176).
    """
    if restart is None:
        restart = build

    selected = _resolve_instances(instances)

    _preflight_checks()
    _confirm_prod_db_rebuild(selected, load_db=load_db, preprocess=preprocess)

    # Step 1 — git push
    if no_push:
        click.secho("\n[1/5] Skipping git push (--no-push)", bold=True)
    else:
        _step_push()

    _run_build_pipeline(
        selected,
        load_db=load_db,
        build=build,
        restart=restart,
        preprocess=preprocess,
        run_tests=run_tests,
        include_meta_analysis=include_meta_analysis,
    )
