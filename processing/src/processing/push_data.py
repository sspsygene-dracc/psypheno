"""Push gitignored dataset *data payloads* up to a server instance.

The push-direction mirror of ``sspsygene pull-data`` (issue #203, items 1.2/1.3).
Where ``pull-data`` pulls missing data files *down* from a reference instance,
``push-data`` pushes the gitignored data files of explicitly-named datasets
*up* to a server instance's ``/hive`` tree.

Why a dedicated command instead of the old manual ``rsync -av
data/datasets/<name>/ …``:

- **Only the gitignored payloads travel.** The file list comes from
  ``git ls-files --others --ignored --exclude-standard`` run inside the dataset
  dir, so tracked files (``config.yaml``, ``preprocess.py``, ``makeDoc.txt``,
  ``expected_drops.yaml``, ``.gitignore``) are *never* pushed — they reach the
  server through ``git pull``. The old ``-av`` copied everything, dirtying the
  server's git tree and breaking the next ``git pull`` (§1.2a).
- **Group-write is preserved.** The remote dataset dir is created (if missing)
  with ``mkdir -p`` + ``chmod g+ws`` and rsync runs with
  ``--perms --chmod=Dg+ws,Fg+w`` so files/dirs land group-writable for the
  ``protein`` group, not mode 644/755 owned solely by the pusher (§1.2b/1.2c/
  §1.3) — otherwise the next wrangler can't overwrite them.

Reuses ``pull_data``'s rsync transport/streaming helpers — this is the same
``/hive``-over-``hgwdev`` plumbing, just running in the opposite direction.
"""

from __future__ import annotations

import shlex
import subprocess
import tempfile
from pathlib import Path

import click
import yaml

from processing.deploy import INSTANCE_PATHS
from processing.pull_data import (
    EXCLUDES,
    _local_datasets_dir,
    _rsync_one,
    _rsync_transport,
    _ssh_prefix,
)


def _gitignored_files(dataset_dir: Path) -> list[str]:
    """Return the gitignored files under *dataset_dir*, relative to it.

    ``git ls-files`` run with cwd inside the dataset dir scopes to that dir and
    emits dir-relative paths, so the result feeds straight into rsync
    ``--files-from`` against a source of ``dataset_dir/``. Tracked files
    (config.yaml, preprocess.py, …) are excluded by construction.
    """
    result = subprocess.run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard"],
        cwd=str(dataset_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise click.ClickException(
            f"`git ls-files` failed in {dataset_dir}:\n"
            f"{(result.stderr or result.stdout).strip()}"
        )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _config_in_paths(dataset_dir: Path) -> list[str]:
    """Return every ``in_path`` declared in the dataset's config.yaml.

    ``in_path`` is interpreted relative to the dir containing config.yaml (see
    config.py), so the returned values are dataset-dir-relative. Returns an
    empty list when there's no config.yaml or it can't be parsed — this is only
    used to *warn*, never to fail the push.
    """
    cfg = dataset_dir / "config.yaml"
    if not cfg.is_file():
        return []
    try:
        with open(cfg) as f:
            loaded = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return []
    if not isinstance(loaded, dict):
        return []
    in_paths: list[str] = []
    for table in loaded.get("tables", []) or []:
        if isinstance(table, dict) and table.get("in_path"):
            in_paths.append(str(table["in_path"]))
    return in_paths


def _remote_files(host: str, remote_dataset_dir: str) -> set[str]:
    """List files present under *remote_dataset_dir*, relative to it.

    Returns an empty set if the dir doesn't exist yet (fresh dataset). Used only
    to decide whether to warn about a missing ``in_path`` file, so a failure
    here is non-fatal.
    """
    cmd = [
        *_ssh_prefix(host),
        f"find {shlex.quote(remote_dataset_dir)} -type f -printf '%P\\n' 2>/dev/null || true",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return {line for line in result.stdout.splitlines() if line.strip()}


def _ensure_remote_dir(host: str, remote_dataset_dir: str, dry_run: bool) -> None:
    """Create the remote dataset dir group-writable (mkdir -p + chmod g+ws)."""
    quoted = shlex.quote(remote_dataset_dir)
    if dry_run:
        click.echo(f"        [dry-run] mkdir -p {remote_dataset_dir} && chmod g+ws")
        return
    cmd = [
        *_ssh_prefix(host),
        f"mkdir -p {quoted} && chmod g+ws {quoted}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise click.ClickException(
            f"Could not create remote dir {host}:{remote_dataset_dir}\n"
            f"{(result.stderr or result.stdout).strip()}"
        )


def run_push_data(
    *,
    datasets: tuple[str, ...],
    instance: str,
    host: str,
    dry_run: bool,
) -> None:
    """Push the gitignored data payloads of *datasets* up to *instance*."""
    if not datasets:
        raise click.ClickException(
            "Name at least one dataset to push (there is no implicit 'all')."
        )
    if instance not in INSTANCE_PATHS:
        raise click.ClickException(
            f"--instance must be one of {', '.join(INSTANCE_PATHS)}; got '{instance}'."
        )
    remote_root = INSTANCE_PATHS[instance]
    local_datasets, root = _local_datasets_dir()
    if not local_datasets.is_dir():
        raise click.ClickException(f"Local datasets dir not found: {local_datasets}")
    remote_datasets = f"{remote_root}/data/{root}"

    transport, rsync_host = _rsync_transport(host)

    click.echo(
        f"Pushing gitignored data files to {instance} "
        f"({rsync_host}:{remote_datasets})"
        + ("  [DRY RUN]" if dry_run else "")
    )

    n = len(datasets)
    total_files = 0
    for i, name in enumerate(datasets, 1):
        dataset_dir = local_datasets / name
        if not dataset_dir.is_dir():
            raise click.ClickException(
                f"No local dataset directory '{name}' under {local_datasets}."
            )

        files = _gitignored_files(dataset_dir)
        remote_dataset_dir = f"{remote_datasets}/{name}"

        if not files:
            click.echo(
                f"  [{i}/{n}] {name}: no gitignored data files to push (skipping)"
            )
            _warn_missing_in_paths(dataset_dir, host, remote_dataset_dir)
            continue

        click.echo(
            f"  [{i}/{n}] {name}: {'would push' if dry_run else 'pushing'} "
            f"{len(files)} gitignored file(s)…"
        )

        _ensure_remote_dir(host, remote_dataset_dir, dry_run)

        # Feed the explicit file list through --files-from. --no-relative keeps
        # the paths relative to the dataset dir (source) rather than recreating
        # data/datasets/<name>/ from the repo root, so nothing touches the perms
        # of shared parent dirs we may not own. --chmod keeps group-write.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".files-from", delete=True
        ) as tf:
            tf.write("\n".join(files) + "\n")
            tf.flush()
            cmd = [
                "rsync",
                "-a",
                "--out-format=%n",
                "--perms",
                "--chmod=Dg+ws,Fg+w",
                "--no-relative",
                f"--files-from={tf.name}",
                "-e",
                transport,
            ]
            for pat in EXCLUDES:
                cmd += ["--exclude", pat]
            if dry_run:
                cmd.append("-n")
            cmd += [
                f"{dataset_dir}/",
                f"{rsync_host}:{remote_dataset_dir}/",
            ]
            count = _rsync_one(cmd, name)

        total_files += count
        verb = "would push" if dry_run else "pushed"
        click.echo(f"        → {verb} {count} file(s)")

        _warn_missing_in_paths(dataset_dir, host, remote_dataset_dir)

    click.echo(
        f"\nDone. {total_files} file(s) across {n} dataset(s)"
        f"{' (dry run — nothing written)' if dry_run else ''}."
    )


def _warn_missing_in_paths(
    dataset_dir: Path,
    host: str,
    remote_dataset_dir: str,
) -> None:
    """Warn about any config.yaml ``in_path`` absent both locally and remotely.

    A missing in_path means ``load-db`` on the server will fail on that file, so
    surfacing it at push time (rather than at deploy time) saves a round trip.
    The remote listing is fetched lazily — only when an in_path is missing
    locally — so the common (everything-present) case costs no extra SSH.
    """
    missing_local = [
        rel for rel in _config_in_paths(dataset_dir) if not (dataset_dir / rel).exists()
    ]
    if not missing_local:
        return
    remote_files = _remote_files(host, remote_dataset_dir)
    for rel in missing_local:
        # remote_files is relative to the remote dataset dir; in_path may
        # include subdirs, compare as-is.
        if rel in remote_files:
            continue
        click.secho(
            f"        ! in_path '{rel}' is absent both locally and on "
            f"{host}:{remote_dataset_dir} — load-db will fail on it until it's "
            "produced (preprocess.py) or pushed.",
            fg="yellow",
        )
