"""Run dataset ``preprocess.py`` scripts locally to (re)generate data files.

``sspsygene deploy --preprocess`` runs each dataset's ``preprocess.py`` on the
server; this is the local equivalent. The cleaned ``<table>.tsv`` / ``.csv``
outputs that ``in_path`` points at are gitignored and *produced* by
``preprocess.py`` from the raw download — so a fresh checkout, or one populated
by ``sspsygene pull-data`` (which only pulls files that already exist on the
server), is still missing any output the server never persisted.

By default this runs ``preprocess.py`` only for datasets that are actually
missing an ``in_path`` file; pass ``--all`` to run every dataset's script.
Each runs in its own directory with the current Python interpreter (the venv
``sspsygene`` itself runs under), so ``import processing.preprocessing`` resolves.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path

import click
import yaml

PREPROCESS_TIMEOUT = 1800
DEFAULT_WORKERS = 8


def _local_datasets_dir() -> Path:
    """Resolve the local ``data/datasets`` directory from the environment."""
    data_dir = os.environ.get("SSPSYGENE_DATA_DIR")
    if not data_dir:
        raise click.ClickException(
            "SSPSYGENE_DATA_DIR is not set (see docs/development.md)."
        )
    root = "datasets"
    cfg = os.environ.get("SSPSYGENE_CONFIG_JSON")
    if cfg and Path(cfg).exists():
        try:
            with open(cfg) as f:
                root = json.load(f).get("table_config_root", "datasets")
        except (json.JSONDecodeError, OSError):
            pass
    return Path(data_dir) / root


def _missing_inpaths(dataset_dir: Path) -> list[str]:
    """``in_path`` files declared by the dataset's config.yaml that are absent."""
    cfg = dataset_dir / "config.yaml"
    if not cfg.exists():
        return []
    try:
        with open(cfg) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError:
        return []
    missing = []
    for table in data.get("tables", []):
        in_path = table.get("in_path")
        if in_path and not (dataset_dir / in_path).exists():
            missing.append(in_path)
    return missing


def _run_one(dataset_dir: Path) -> tuple[str, int, str]:
    try:
        proc = subprocess.run(
            [sys.executable, "preprocess.py"],
            cwd=dataset_dir,
            capture_output=True,
            text=True,
            timeout=PREPROCESS_TIMEOUT,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return dataset_dir.name, -1, f"Timed out after {PREPROCESS_TIMEOUT}s"
    return dataset_dir.name, proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_local_preprocess(
    *,
    dataset: str | None,
    run_all: bool,
    dry_run: bool,
    max_workers: int,
) -> None:
    """Run ``preprocess.py`` for datasets missing an ``in_path`` file (or *all*)."""
    datasets_dir = _local_datasets_dir()
    if not datasets_dir.is_dir():
        raise click.ClickException(f"Local datasets dir not found: {datasets_dir}")

    with_script = sorted(p.parent for p in datasets_dir.glob("*/preprocess.py"))

    if dataset:
        if not (datasets_dir / dataset).is_dir():
            raise click.ClickException(f"No local dataset directory '{dataset}'.")
        targets = [d for d in with_script if d.name == dataset]
        if not targets:
            raise click.ClickException(f"Dataset '{dataset}' has no preprocess.py.")
    elif run_all:
        targets = with_script
    else:
        targets = [d for d in with_script if _missing_inpaths(d)]

    if not targets:
        click.echo(
            "No datasets have a preprocess.py."
            if run_all
            else "Nothing to do — every dataset's in_path files are present. "
            "(Pass --all to re-run preprocess.py everywhere.)"
        )
        return

    click.echo(
        f"Running preprocess.py for {len(targets)} dataset(s)"
        + (" [DRY RUN]" if dry_run else "") + ":"
    )
    for d in targets:
        miss = _missing_inpaths(d)
        why = f"  (missing: {', '.join(miss)})" if miss and not run_all else ""
        click.echo(f"  - {d.name}{why}")
    if dry_run:
        click.echo("\nDry run — nothing executed.")
        return

    workers = max(1, min(max_workers, len(targets)))
    click.echo(f"\nExecuting with {workers} parallel worker(s)…\n")
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_one, d) for d in targets]
        for future in concurrent.futures.as_completed(futures):
            name, rc, output = future.result()
            if rc == 0:
                click.echo(f"  OK   {name}")
            else:
                click.secho(f"  FAIL {name} (exit {rc})", fg="red")
                for line in output.strip().splitlines()[-25:]:
                    click.echo(f"    | {line}")
                failures.append(name)

    if failures:
        raise click.ClickException(
            f"{len(failures)} of {len(targets)} preprocess run(s) failed: "
            + ", ".join(failures)
        )
    click.echo(f"\nDone. {len(targets)} dataset(s) preprocessed successfully.")
