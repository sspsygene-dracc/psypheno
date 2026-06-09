"""Sync missing dataset data files from a reference instance down to localhost.

Per-dataset *data* files — raw downloads (``*.xlsx`` / ``*.csv`` / ``*.tsv`` /
``*.txt``) and the cleaned ``<table>.tsv`` outputs that ``in_path`` points at —
are gitignored, so they never travel through ``git pull``. A fresh checkout, or
any dataset whose data was only ever built on the server, is therefore missing
the inputs ``load-db`` needs (you see ``FileNotFoundError`` on ``in_path``).

``sspsygene sync-data`` rsyncs those missing files down from a reference
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


def run_sync_data(
    *,
    dataset: str | None,
    instance: str,
    host: str,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Pull missing (or, with *overwrite*, also stale) data files from *instance*."""
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
    click.echo(
        f"\nDone. {total_files} file(s) across {synced} dataset(s)"
        f"{' (dry run — nothing written)' if dry_run else ''}; "
        f"{skipped} dataset(s) not on {instance}."
    )
