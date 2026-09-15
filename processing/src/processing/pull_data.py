"""Sync missing dataset data files from a reference instance down to localhost.

Per-dataset *data* files — raw downloads (``*.xlsx`` / ``*.csv`` / ``*.tsv`` /
``*.txt``) and the cleaned ``<table>.tsv`` outputs that ``in_path`` points at —
are gitignored, so they never travel through ``git pull``. A fresh checkout, or
any dataset whose data was only ever built on the server, is therefore missing
the inputs ``load-db`` needs (you see ``FileNotFoundError`` on ``in_path``).

``sspsygene pull-data`` rsyncs those missing files down from a reference
instance — **dev by default**, which is effectively a superset of int and prod
— *without overwriting anything that already exists locally*. Tracked files
(``config.yaml``, ``preprocess.py``, …) come from git and are always present, so
in practice only the gitignored data files get pulled.

All three instance trees live under ``/hive`` and are readable from ``hgwdev``,
so we read straight off ``/hive`` over a single ``hgwdev`` SSH connection rather
than proxying through psygene.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from collections import deque
from functools import lru_cache
from pathlib import Path

import click
from tqdm import tqdm

from processing.deploy import (
    PSYGENE,
    PSYGENE_PROXY_JUMP,
    PSYGENE_SSH_HOST,
)
from processing.instances import INSTANCE_PATHS  # noqa: F401  (re-exported)

# hgwdev is directly reachable and shares /hive with psygene, so it can read
# every instance's tree without a ProxyJump. It's the right default reference
# host for a read-only data pull.
DEFAULT_HOST = "hgwdev"


def _ssh_prefix(host: str) -> list[str]:
    """SSH argv prefix for *host* (proxy-jumping for psygene, direct otherwise)."""
    opts = ["ssh", "-o", "StrictHostKeyChecking=accept-new"]
    if host == PSYGENE:
        return [*opts, "-J", PSYGENE_PROXY_JUMP, PSYGENE_SSH_HOST]
    return [*opts, host]


# rsync filters: editor/OS cruft that occasionally litters the server tree but
# is never real dataset data. Keeps a fresh local checkout clean.
#
# `expected_drops.yaml*` is excluded on purpose: the committed manifest
# (`expected_drops.yaml`) travels through git, and the `.proposed` sidecar is a
# transient artifact the data-correspondence test writes into a working tree for
# the wrangler to review and merge by hand. Neither should be rsynced down —
# pulling the `.proposed` files just littered every checkout with untracked
# files (they're not gitignored, so they show up in `git status`).
EXCLUDES = ("*~", "*.swp", "*.orig", ".DS_Store", "expected_drops.yaml*")


# A transfer carrying at least one file this big gets a tqdm progress bar with
# an ETA. Below it, rsync finishes before a bar would have told you anything,
# and the per-file names it already streams are the more useful output.
PROGRESS_MIN_FILE_BYTES = 50 * 1024 * 1024

# `--info=progress2` emits a running "<bytes> <pct>% <rate> <eta>" chunk for the
# transfer as a whole, separated by \r rather than \n. We only read the byte
# count off it — tqdm derives rate and ETA itself, so a stalled connection shows
# a decaying rate instead of rsync's last-known figure.
_PROGRESS_RE = re.compile(r"^\s*([\d,]+)\s+\d+%\s+\S+\s+\d+:\d\d:\d\d")


@lru_cache(maxsize=1)
def _rsync_supports_progress() -> bool:
    """Whether the local rsync understands ``--info=progress2``.

    macOS ships openrsync, which doesn't have ``--info`` at all — passing it
    there aborts the transfer. A wrangler on stock macOS therefore keeps the
    old filename-streaming output instead of getting an error.
    """
    try:
        result = subprocess.run(
            ["rsync", "--info=help"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "PROGRESS" in result.stdout


def _rsync_transport(host: str) -> tuple[str, str]:
    """Return (``-e`` transport string, rsync hostname) for *host*."""
    transport = "ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20"
    if host == PSYGENE:
        return f"{transport} -J {PSYGENE_PROXY_JUMP}", PSYGENE_SSH_HOST
    return transport, host


def _rsync_one(
    cmd: list[str],
    name: str,
    *,
    progress_total: int | None = None,
) -> int:
    """Run an rsync, streaming each transferred filename live; return the count.

    Streaming (rather than capturing) means a big dataset shows files ticking by
    instead of going silent until the whole transfer finishes.

    When *progress_total* is given (the caller has decided this transfer carries
    a file worth waiting on — see ``PROGRESS_MIN_FILE_BYTES``) the transfer also
    gets a tqdm bar with an ETA, fed by rsync's own ``--info=progress2`` byte
    counter. *progress_total* is an estimate: rsync skips files that are already
    up to date, so the bar can finish short of its total. It's set `leave=False`
    so it disappears on completion and the caller's "synced N file(s)" summary
    is what remains on screen.
    """
    bar = None
    if progress_total and _rsync_supports_progress():
        cmd = [*cmd, "--info=progress2"]
        bar = tqdm(
            total=progress_total,
            desc=f"        {name}",
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            dynamic_ncols=True,
            leave=False,
            # disable=None auto-disables when stderr isn't a TTY, so deploy
            # logs and CI capture don't fill up with redrawn bars.
            disable=None,
        )

    def emit(line: str) -> None:
        # tqdm.write keeps the bar pinned to the bottom instead of having the
        # filename lines shred it.
        if bar is not None:
            tqdm.write(f"        {line}")
        else:
            click.echo(f"        {line}")

    # Binary + unbuffered: rsync separates progress updates with \r, which
    # text-mode line iteration would swallow into one enormous "line" that only
    # flushes when the file finishes — exactly the case the bar exists for.
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0
    )
    count = 0
    transferred = 0
    tail: deque[str] = deque(maxlen=30)
    assert proc.stdout is not None
    buf = b""
    try:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            buf += chunk
            pieces = re.split(rb"[\r\n]", buf)
            # The last piece may be a partial line; hold it until more arrives.
            buf = pieces.pop()
            for raw in pieces:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                match = _PROGRESS_RE.match(line)
                if match:
                    if bar is not None:
                        done = int(match.group(1).replace(",", ""))
                        # progress2's counter is cumulative for the whole
                        # transfer, so advance by the delta.
                        bar.update(max(0, min(done, progress_total) - transferred))
                        transferred = done
                    continue
                tail.append(line)
                # --out-format=%n emits one line per item; skip dirs + rsync's
                # own status lines so we count (and echo) only real files.
                if line.endswith("/") or line.startswith("rsync"):
                    continue
                count += 1
                emit(line)
        if buf.strip():
            tail.append(buf.decode("utf-8", errors="replace").rstrip())
    finally:
        if bar is not None:
            bar.close()
    if proc.wait() != 0:
        raise click.ClickException(
            f"rsync failed for '{name}':\n" + "\n".join(tail)
        )
    return count


def _local_datasets_dir() -> tuple[Path, str]:
    """Resolve the local ``data/datasets`` directory + its root name from env."""
    data_dir = os.environ.get("SSPSYGENE_DATA_DIR")
    if not data_dir:
        raise click.ClickException(
            "SSPSYGENE_DATA_DIR is not set (see docs/development.md)."
        )
    root = "datasets"
    cfg_json = os.environ.get("SSPSYGENE_CONFIG_JSON")
    if cfg_json and Path(cfg_json).exists():
        try:
            with open(cfg_json) as f:
                root = json.load(f).get("table_config_root", "datasets")
        except (json.JSONDecodeError, OSError):
            pass
    return Path(data_dir) / root, root


def _list_remote_dirs(host: str, remote_datasets: str) -> set[str]:
    cmd = [*_ssh_prefix(host), f"ls -1 {shlex.quote(remote_datasets)}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise click.ClickException(
            f"Could not list remote datasets at {host}:{remote_datasets}\n"
            f"{(result.stderr or result.stdout).strip()}"
        )
    return set(result.stdout.split())


def _shared_input_relpaths() -> list[str]:
    """Relative-to-data-dir paths of the shared/global inputs ``load-db`` needs.

    Read straight from ``config.json``'s ``gene_map_files`` — the authoritative
    list of cross-dataset gene-reference inputs (HGNC / MGI / Alliance homology /
    …) — rather than hardcoding filenames here, so new shared inputs are picked
    up automatically once they're added to the config. Most of these are
    gitignored, which is exactly why a fresh checkout needs them pulled.
    """
    cfg_json = os.environ.get("SSPSYGENE_CONFIG_JSON")
    if not cfg_json or not Path(cfg_json).exists():
        return []
    try:
        with open(cfg_json) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    gene_map = cfg.get("gene_map_files", {})
    seen: set[str] = set()
    relpaths: list[str] = []
    for value in gene_map.values():
        if value and value not in seen:
            seen.add(value)
            relpaths.append(str(value))
    return relpaths


def _sync_shared_inputs(
    *,
    host: str,
    remote_root: str,
    instance: str,
    overwrite: bool,
    dry_run: bool,
) -> tuple[int, int]:
    """Pull the shared/global gene-reference inputs ``load-db`` depends on.

    These are the cross-dataset files in ``config.json``'s ``gene_map_files``
    (homology / HGNC / MGI / Alliance / …). Most are gitignored, so a fresh
    checkout lacks them and ``load-db`` dies on a missing path. We rsync each one
    that's missing locally from the reference instance's ``/hive`` tree; entries
    that arrived via git (already present) are skipped, so in practice only the
    gitignored homology files transfer. ``--ignore-missing-args`` keeps an input
    the server happens not to carry from failing the whole sync.

    Returns ``(files_transferred, inputs_synced)``.
    """
    relpaths = _shared_input_relpaths()
    if not relpaths:
        click.echo(
            "\nNo shared inputs configured (gene_map_files empty / config "
            "unreadable); skipping shared-input sync."
        )
        return 0, 0

    data_dir = Path(os.environ["SSPSYGENE_DATA_DIR"])
    transport, rsync_host = _rsync_transport(host)
    click.echo(
        "\nSyncing shared/global inputs (homology + gene-reference tables) "
        f"from {instance}" + ("  [DRY RUN]" if dry_run else "")
    )

    # Only fetch inputs missing locally (unless --overwrite). Tracked entries
    # arrive via git and are skipped here.
    wanted = [rel for rel in relpaths if overwrite or not (data_dir / rel).exists()]
    for rel in relpaths:
        if rel not in wanted:
            click.echo(f"  {rel}: present, skipping")

    # Probe remote existence once up front. openrsync (the macOS default) has no
    # --ignore-missing-args, so rsyncing a path the server doesn't carry would
    # abort the whole run; checking first lets us skip those cleanly.
    remote_paths = {rel: f"{remote_root}/data/{rel}" for rel in wanted}
    remote_present = _list_remote_files(host, list(remote_paths.values()))
    remote_sizes: dict[str, int] = {}
    if not dry_run and _rsync_supports_progress():
        remote_sizes = _remote_sizes_of(host, sorted(remote_present))

    total_files = 0
    synced = 0
    for rel in wanted:
        if remote_paths[rel] not in remote_present:
            click.echo(f"  {rel}: not present on {instance}, skipping")
            continue
        local_path = data_dir / rel
        local_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["rsync", "-a", "--out-format=%n", "-e", transport]
        for pat in EXCLUDES:
            cmd += ["--exclude", pat]
        if not overwrite:
            cmd.append("--ignore-existing")
        if dry_run:
            cmd.append("-n")
        cmd += [
            f"{rsync_host}:{remote_paths[rel]}",
            str(local_path),
        ]
        click.echo(f"  {rel}: {'checking' if dry_run else 'syncing'}…")
        # Homology tables are among the biggest files we move (MGI_EntrezGene
        # and friends run past 50 MB), so they get a bar too.
        size = remote_sizes.get(remote_paths[rel])
        count = _rsync_one(
            cmd,
            rel,
            progress_total=(
                size if size and size >= PROGRESS_MIN_FILE_BYTES else None
            ),
        )
        if count:
            synced += 1
            total_files += count
            verb = "would sync" if dry_run else "synced"
            click.echo(f"        → {verb} {count} file(s)")
        else:
            click.echo("        → already up to date")
    return total_files, synced


def _remote_file_sizes(host: str, remote_dir: str) -> dict[str, int]:
    """``{path relative to remote_dir: size in bytes}`` for files under it.

    One SSH round trip for the whole tree, used only to decide which datasets
    warrant a progress bar and what to size it against. Best-effort: any failure
    returns an empty mapping and the transfer runs without a bar rather than
    failing over a cosmetic feature.
    """
    cmd = [
        *_ssh_prefix(host),
        f"find {shlex.quote(remote_dir)} -type f -printf '%s\\t%P\\n' "
        f"2>/dev/null || true",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return {}
    sizes: dict[str, int] = {}
    for line in result.stdout.splitlines():
        size, tab, rel = line.partition("\t")
        if not tab or not rel:
            continue
        try:
            sizes[rel] = int(size)
        except ValueError:
            continue
    return sizes


def _remote_sizes_of(host: str, paths: list[str]) -> dict[str, int]:
    """``{path: size in bytes}`` for an explicit list of remote *paths*.

    The shared-input counterpart of :func:`_remote_file_sizes` (which walks a
    whole tree). Best-effort, same reasoning: a failure means no progress bar,
    never a failed sync.
    """
    if not paths:
        return {}
    script = "; ".join(
        f"stat -c '%s\t%n' {shlex.quote(path)} 2>/dev/null" for path in paths
    )
    try:
        result = subprocess.run(
            [*_ssh_prefix(host), script], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    sizes: dict[str, int] = {}
    for line in result.stdout.splitlines():
        size, tab, path = line.partition("\t")
        if not tab or not path:
            continue
        try:
            sizes[path] = int(size)
        except ValueError:
            continue
    return sizes


def _progress_total(
    sizes: dict[str, int],
    wanted: list[str],
) -> int | None:
    """Bytes to size a progress bar against, or None if no bar is warranted.

    A bar is warranted only when at least one file in *wanted* is at or above
    ``PROGRESS_MIN_FILE_BYTES`` — the case where a transfer goes quiet for long
    enough that an ETA is worth having.
    """
    present = [sizes[rel] for rel in wanted if rel in sizes]
    if not present or max(present) < PROGRESS_MIN_FILE_BYTES:
        return None
    return sum(present)


def _list_remote_files(host: str, paths: list[str]) -> set[str]:
    """Return the subset of *paths* that exist on *host* (single SSH round-trip).

    Used to skip shared inputs the reference instance happens not to carry,
    without depending on rsync's ``--ignore-missing-args`` (absent from the macOS
    default openrsync).
    """
    if not paths:
        return set()
    # One `test -e` per path; echo the ones that exist.
    script = "; ".join(
        f"test -e {shlex.quote(p)} && echo {shlex.quote(p)}" for p in paths
    )
    cmd = [*_ssh_prefix(host), script]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    # A trailing `&&` chain makes the exit status reflect the last test, so a
    # nonzero return just means the last path was absent — don't treat it as a
    # connection failure. Parse stdout regardless.
    return {line for line in result.stdout.split("\n") if line}


def run_pull_data(
    *,
    dataset: str | None,
    instance: str,
    host: str,
    overwrite: bool,
    dry_run: bool,
    shared: bool = True,
) -> None:
    """Pull missing (or, with *overwrite*, also stale) data files from *instance*.

    By default also pulls the shared/global gene-reference inputs (homology, …)
    that ``load-db`` needs; pass ``shared=False`` to sync only dataset files.
    """
    if instance not in INSTANCE_PATHS:
        raise click.ClickException(
            f"--instance must be one of {', '.join(INSTANCE_PATHS)}; got '{instance}'."
        )
    remote_root = INSTANCE_PATHS[instance]
    local_datasets, root = _local_datasets_dir()
    remote_datasets = f"{remote_root}/data/{root}"
    if not local_datasets.is_dir():
        raise click.ClickException(f"Local datasets dir not found: {local_datasets}")

    transport, rsync_host = _rsync_transport(host)

    shared_files = shared_synced = 0
    if shared:
        shared_files, shared_synced = _sync_shared_inputs(
            host=host,
            remote_root=remote_root,
            instance=instance,
            overwrite=overwrite,
            dry_run=dry_run,
        )

    if dataset:
        if not (local_datasets / dataset).is_dir():
            raise click.ClickException(
                f"No local dataset directory '{dataset}' under {local_datasets}."
            )
        names = [dataset]
    else:
        names = sorted(p.name for p in local_datasets.iterdir() if p.is_dir())

    click.echo(
        f"Syncing missing data files from {instance} "
        f"({rsync_host}:{remote_datasets}) -> {local_datasets}"
        + ("  [DRY RUN]" if dry_run else "")
    )

    remote_dirs = _list_remote_dirs(host, remote_datasets)

    # Sizes for the whole remote datasets tree in one round trip, so each
    # dataset's transfer knows whether it's carrying anything big enough to
    # deserve a progress bar. Skipped when nothing will transfer (dry run) or
    # the local rsync can't report progress anyway.
    remote_sizes: dict[str, int] = {}
    if not dry_run and _rsync_supports_progress():
        remote_sizes = _remote_file_sizes(host, remote_datasets)

    total_files = 0
    synced = skipped = 0
    n = len(names)
    for i, name in enumerate(names, 1):
        if name not in remote_dirs:
            click.echo(f"  [{i}/{n}] {name}: not on {instance}, skipping")
            skipped += 1
            continue
        cmd = ["rsync", "-a", "--out-format=%n", "-e", transport]
        for pat in EXCLUDES:
            cmd += ["--exclude", pat]
        if not overwrite:
            cmd.append("--ignore-existing")
        if dry_run:
            cmd.append("-n")
        cmd += [
            f"{rsync_host}:{remote_datasets}/{name}/",
            f"{local_datasets}/{name}/",
        ]
        # Without --overwrite rsync skips what's already here, so only the
        # locally-missing files count toward the bar.
        prefix = f"{name}/"
        candidates = [
            rel
            for rel in remote_sizes
            if rel.startswith(prefix)
            and (overwrite or not (local_datasets / rel).exists())
        ]
        click.echo(f"  [{i}/{n}] {name}: {'checking' if dry_run else 'syncing'}…")
        count = _rsync_one(
            cmd, name, progress_total=_progress_total(remote_sizes, candidates)
        )
        if count:
            synced += 1
            total_files += count
            verb = "would sync" if dry_run else "synced"
            click.echo(f"        → {verb} {count} file(s)")
        else:
            click.echo("        → already up to date")
    shared_note = (
        f" plus {shared_files} shared-input file(s) across {shared_synced} input(s)"
        if shared
        else ""
    )
    click.echo(
        f"\nDone. {total_files} dataset file(s) across {synced} dataset(s)"
        f"{shared_note}"
        f"{' (dry run — nothing written)' if dry_run else ''}; "
        f"{skipped} dataset(s) not on {instance}."
    )
