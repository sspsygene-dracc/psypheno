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
import shlex
import subprocess
from collections import deque
from pathlib import Path

import click

from processing.deploy import (
    DEV_PATH,
    INT_PATH,
    PROD_PATH,
    PSYGENE,
    PSYGENE_PROXY_JUMP,
    PSYGENE_SSH_HOST,
)

# hgwdev is directly reachable and shares /hive with psygene, so it can read
# every instance's tree without a ProxyJump. It's the right default reference
# host for a read-only data pull.
DEFAULT_HOST = "hgwdev"

INSTANCE_PATHS = {"dev": DEV_PATH, "int": INT_PATH, "prod": PROD_PATH}


def _ssh_prefix(host: str) -> list[str]:
    """SSH argv prefix for *host* (proxy-jumping for psygene, direct otherwise)."""
    opts = ["ssh", "-o", "StrictHostKeyChecking=accept-new"]
    if host == PSYGENE:
        return [*opts, "-J", PSYGENE_PROXY_JUMP, PSYGENE_SSH_HOST]
    return [*opts, host]


# rsync filters: editor/OS cruft that occasionally litters the server tree but
# is never real dataset data. Keeps a fresh local checkout clean.
EXCLUDES = ("*~", "*.swp", "*.orig", ".DS_Store")


def _rsync_transport(host: str) -> tuple[str, str]:
    """Return (``-e`` transport string, rsync hostname) for *host*."""
    transport = "ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20"
    if host == PSYGENE:
        return f"{transport} -J {PSYGENE_PROXY_JUMP}", PSYGENE_SSH_HOST
    return transport, host


def _rsync_one(cmd: list[str], name: str) -> int:
    """Run an rsync, streaming each transferred filename live; return the count.

    Streaming (rather than capturing) means a big dataset shows files ticking by
    instead of going silent until the whole transfer finishes.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    count = 0
    tail: deque[str] = deque(maxlen=30)
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        tail.append(line)
        # --out-format=%n emits one line per item; skip dirs + rsync's own
        # status lines so we count (and echo) only real files.
        if not line or line.endswith("/") or line.startswith("rsync"):
            continue
        count += 1
        click.echo(f"        {line}")
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
        count = _rsync_one(cmd, rel)
        if count:
            synced += 1
            total_files += count
            verb = "would sync" if dry_run else "synced"
            click.echo(f"        → {verb} {count} file(s)")
        else:
            click.echo("        → already up to date")
    return total_files, synced


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
        click.echo(f"  [{i}/{n}] {name}: {'checking' if dry_run else 'syncing'}…")
        count = _rsync_one(cmd, name)
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
