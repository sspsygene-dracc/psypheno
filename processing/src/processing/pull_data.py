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
from collections.abc import Iterator
from contextlib import contextmanager
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

# rsync's classic `--progress` emits, per file, a run of
# "<bytes> <pct>% <rate> <eta>" updates separated by \r rather than \n (the
# last one carrying a trailing "(xfer#N, to-check=…)"). We read the byte count
# off it and let tqdm derive rate and ETA, so a stalled connection decays
# toward "no idea" instead of showing rsync's last good figure.
_PROGRESS_RE = re.compile(r"^\s*([\d,]+)\s+\d+%\s+\S+\s+\d+:\d\d:\d\d")


@lru_cache(maxsize=1)
def _rsync_supports_progress() -> bool:
    """Whether the local rsync understands the classic ``--progress`` flag.

    It has been in rsync since the 2.x days and macOS's stock openrsync has
    it too, so this should be true everywhere — but a bar must never be the
    reason a sync fails, so an unusable rsync just means no bar.

    Note for anyone tempted to use the newer ``--info=progress2`` instead:
    openrsync has no ``--info`` at all, so on a stock Mac that flag aborts
    the transfer. ``--progress`` is the portable spelling (#241).
    """
    try:
        result = subprocess.run(
            ["rsync", "--help"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "--progress" in result.stdout


class _TransferBar:
    """One tqdm bar for a whole operation, fed by rsync's own byte counter.

    ``--progress`` restarts its counter at every file, so an operation that
    moves several files (or spans several rsync invocations — one per dataset)
    has to bank each finished file's bytes and add the in-flight file's count
    on top. That keeps a single bar advancing monotonically across the whole
    push or pull rather than resetting per file.

    The numbers come from rsync itself, which is the only thing that actually
    knows how much of a delta transfer has moved. An earlier attempt polled
    the destination file's size instead; that reads as ~100% almost
    immediately, because rsync sets the file to its final length up front and
    then fills blocks in, so size is not a proxy for progress (#242).
    """

    def __init__(self, total: int, desc: str) -> None:
        self._bar = tqdm(
            total=total,
            desc=desc,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            dynamic_ncols=True,
            leave=False,
            # disable=None auto-disables when stderr isn't a TTY, so deploy
            # logs and CI capture don't fill up with redrawn bars.
            disable=None,
        )
        self._banked = 0
        self._current = 0

    def start_file(self) -> None:
        """A new file's transfer began; bank the one that just finished."""
        self._banked += self._current
        self._current = 0

    def note_bytes(self, transferred: int) -> None:
        """rsync reported *transferred* bytes so far for the in-flight file."""
        self._current = transferred
        self._bar.n = min(self._banked + self._current, self._bar.total)
        self._bar.refresh()

    def write(self, line: str) -> None:
        """Print *line* without the bar shredding it."""
        tqdm.write(line)

    def close(self) -> None:
        # The total is an upper bound — rsync skips files already up to date —
        # so a finished run should read as done rather than stalled short.
        self._bar.n = self._bar.total
        self._bar.refresh()
        self._bar.close()


@contextmanager
def _transfer_bar(
    sizes: dict[str, int],
    wanted: list[str],
    desc: str,
) -> Iterator[_TransferBar | None]:
    """One bar for the whole operation, or None when one isn't warranted.

    Callers thread the yielded bar through every ``_rsync_one`` call the
    operation makes, so a push or pull spanning several datasets shows a
    single bar for the lot rather than one per file.
    """
    total = _progress_total(sizes, wanted)
    if total is None or not _rsync_supports_progress():
        yield None
        return
    bar = _TransferBar(total, desc)
    try:
        yield bar
    finally:
        bar.close()


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
    bar: _TransferBar | None = None,
) -> int:
    """Run an rsync, streaming each transferred filename live; return the count.

    Streaming (rather than capturing) means a big dataset shows files ticking
    by instead of going silent until the whole transfer finishes.

    When *bar* is given, ``--progress`` is added and its per-file byte counter
    drives that bar. The same bar is passed to every ``_rsync_one`` of an
    operation, so it advances across all of them rather than restarting.

    Text mode is what makes the parsing work: rsync separates progress updates
    with \\r, and Python's universal-newline translation splits on those, so
    each update arrives as its own line instead of being buffered until the
    file finishes.
    """
    if bar is not None:
        cmd = [*cmd, "--progress"]
    emit = bar.write if bar is not None else click.echo

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        errors="replace",
    )
    count = 0
    tail: deque[str] = deque(maxlen=30)
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        if bar is not None:
            match = _PROGRESS_RE.match(line)
            if match:
                bar.note_bytes(int(match.group(1).replace(",", "")))
                continue
        tail.append(line)
        # --out-format=%n emits one line per item; skip dirs + rsync's own
        # status lines so we count (and echo) only real files.
        if line.endswith("/") or line.startswith("rsync"):
            continue
        count += 1
        # The filename lands before that file's progress updates, so this is
        # where the previous file's bytes get banked.
        if bar is not None:
            bar.start_file()
        emit(f"        {line}")
    retcode = proc.wait()
    if retcode != 0:
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

    # Homology tables are among the biggest files we move (MGI_EntrezGene and
    # friends run past 50 MB), so size the bar against the remote sizes of
    # everything this run will attempt — one bar for the whole shared-input
    # sync rather than one per file.
    sizes: dict[str, int] = {}
    if not dry_run:
        remote_sizes = _remote_sizes_of(host, sorted(remote_present))
        sizes = {
            rel: remote_sizes[remote_paths[rel]]
            for rel in wanted
            if remote_paths[rel] in remote_sizes
        }

    total_files = 0
    synced = 0
    with _transfer_bar(
        sizes,
        list(sizes),
        desc=f"        shared inputs from {instance}",
    ) as bar:
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
            count = _rsync_one(cmd, rel, bar=bar)
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
    enough that an ETA is worth having. The returned total is an upper bound:
    rsync skips files the destination already matches.
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

    # Sizes for the whole remote datasets tree in one round trip, so the whole
    # operation (every dataset in this run) can share one bar sized against
    # what's actually missing locally, instead of one bar per dataset.
    remote_sizes: dict[str, int] = {}
    if not dry_run:
        remote_sizes = _remote_file_sizes(host, remote_datasets)

    # Without --overwrite rsync skips what's already here, so only the
    # locally-missing files count toward the bar.
    candidates = [
        rel
        for name in names
        if name in remote_dirs
        for rel in remote_sizes
        if rel.startswith(f"{name}/")
        and (overwrite or not (local_datasets / rel).exists())
    ]

    total_files = 0
    synced = skipped = 0
    n = len(names)
    with _transfer_bar(
        remote_sizes,
        candidates,
        desc=f"        datasets from {instance}",
    ) as bar:
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
            click.echo(f"  [{i}/{n}] {name}: {'checking' if dry_run else 'syncing'}…")
            count = _rsync_one(cmd, name, bar=bar)
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
