import json
import logging
import sys
import shutil
from pathlib import Path

import click

from processing.click.full_help_group import FullHelpGroup
from processing.config import get_sspsygene_config
from processing.run_llm_search import (
    DEFAULT_MAX_BUDGET,
    DEFAULT_MAX_WORKERS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    VALID_MODELS,
    generate_config,
    run_pipeline,
)


@click.group(
    cls=FullHelpGroup,
    context_settings={"max_content_width": shutil.get_terminal_size().columns - 10},
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
    default="INFO",
)
@click.option("--log-file", type=str, default=None)
def cli(
    log_level: str,
    log_file: str | None,
) -> None:
    """SSPsyGene Website Data Processing"""
    # Plain-message format keeps the INFO chatter readable; WARNINGs and
    # ERRORs are styled inline by the call site (click.style) so the
    # absence of a level prefix doesn't lose them visually.
    fmt = "%(message)s"
    if log_file:
        logging.basicConfig(filename=log_file, level=log_level, format=fmt)
    else:
        logging.basicConfig(level=log_level, stream=sys.stdout, format=fmt)


@cli.command()
@click.option(
    "--dataset",
    type=str,
    default=None,
    help="Load only this dataset directory (e.g. 'mouse-cortex-perturb-4tf'). "
    "If omitted, all datasets are loaded.",
)
@click.option(
    "--skip-missing-datasets",
    is_flag=True,
    default=False,
    help="Skip tables whose input files are missing instead of failing.",
)
@click.option(
    "--no-index",
    is_flag=True,
    default=False,
    help="Skip creating SQLite indexes. Speeds up loading for test purposes.",
)
@click.option(
    "--skip-gene-descriptions",
    is_flag=True,
    default=False,
    help="Skip copying gene descriptions into the database.",
)
@click.option(
    "--skip-meta-analysis",
    is_flag=True,
    default=False,
    help="Skip computing combined p-values (meta-analysis). Speeds up loading for test purposes.",
)
@click.option(
    "--no-r-cache",
    is_flag=True,
    default=False,
    help="Bypass the R meta-analysis result cache (processing/r-cache/). "
    "Forces every R job to re-run; useful when iterating on the R script "
    "before its bytes change.",
)
@click.option(
    "--export-only",
    is_flag=True,
    default=False,
    help="Skip the DB rebuild and only regenerate the user-facing download "
    "blobs (export_files table) inside the existing out_db. Useful while "
    "iterating on the export step.",
)
@click.option(
    "--test",
    "test_mode",
    is_flag=True,
    default=False,
    help="Restrict each dataset to rows whose gene columns all intersect the "
    "bundled top-genes fixture (processing/src/processing/test_fixture_genes.json), "
    "then cap each unique gene-key combo to 200 rows. Fast end-to-end smoke "
    "tests. Orthogonal to --no-index and --skip-meta-analysis.",
)
def load_db(
    dataset: str | None,
    skip_missing_datasets: bool,
    no_index: bool,
    skip_gene_descriptions: bool,
    skip_meta_analysis: bool,
    no_r_cache: bool,
    export_only: bool,
    test_mode: bool,
) -> None:
    """Load the database"""
    try:
        from processing.sq_load import load_db

        config = get_sspsygene_config(dataset=dataset)
        config.out_db.parent.mkdir(parents=True, exist_ok=True)
        if export_only:
            from processing.exports import write_exports

            if not config.out_db.exists():
                click.echo(
                    f"Error: --export-only requires an existing DB at "
                    f"{config.out_db}; run `sspsygene load-db` first.",
                    err=True,
                )
                sys.exit(1)
            write_exports(config.out_db)
            click.echo(
                click.style(
                    f"Wrote exports as BLOBs into {config.out_db}",
                    fg="green",
                    bold=True,
                )
            )
            return
        test_central_gene_ids: set[int] | None = None
        if test_mode:
            fixture_path = (
                Path(__file__).resolve().parent.parent / "test_fixture_genes.json"
            )
            test_central_gene_ids = set(
                json.loads(fixture_path.read_text())["central_gene_ids"]
            )
            click.echo(
                f"--test: filtering to {len(test_central_gene_ids)} central genes "
                f"from {fixture_path.name}"
            )
        load_db(
            config.out_db,
            config.tables_config.tables,
            assay_types=config.global_config.get("assayTypes", {}),
            disease_types=config.global_config.get("diseaseTypes", {}),
            organism_types=config.global_config.get("organismTypes", {}),
            skip_missing=skip_missing_datasets,
            hgnc_path=config.gene_map_config.hgnc_file,
            no_index=no_index,
            data_dir=config.base_dir,
            skip_gene_descriptions=skip_gene_descriptions,
            nimh_csv_path=config.gene_map_config.nimh_gene_list_file,
            tf_list_path=config.gene_map_config.tf_list_file,
            skip_meta_analysis=skip_meta_analysis,
            test_central_gene_ids=test_central_gene_ids,
            use_r_cache=not no_r_cache,
        )
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
def load_gene_descriptions() -> None:
    """Parse NCBI gene_info.gz into a standalone gene_descriptions.db."""
    from processing.gene_descriptions import build_descriptions_db

    config = get_sspsygene_config()
    build_descriptions_db(config.base_dir)


@cli.command(name="run-llm-search")
@click.argument(
    "yaml_file", type=click.Path(exists=True, dir_okay=False, path_type=str)
)
@click.option(
    "--max-workers",
    type=int,
    default=DEFAULT_MAX_WORKERS,
    show_default=True,
    help="Maximum number of concurrent gene search agents.",
)
@click.option(
    "--model",
    type=str,
    default=DEFAULT_MODEL,
    show_default=True,
    help="Model to use (e.g. sonnet, opus).",
)
@click.option(
    "--max-budget",
    type=str,
    default=DEFAULT_MAX_BUDGET,
    show_default=True,
    help="Maximum budget in USD per agent run.",
)
@click.option(
    "--timeout",
    type=int,
    default=DEFAULT_TIMEOUT,
    show_default=True,
    help="Timeout per gene in seconds.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Resolve jobs and print queue/skip info without running agents.",
)
def run_llm_search(
    yaml_file: str,
    max_workers: int,
    model: str,
    max_budget: str,
    timeout: int,
    dry_run: bool,
) -> None:
    """Run parallel LLM gene searches from a YAML job file."""
    if model not in VALID_MODELS:
        valid_models = ", ".join(VALID_MODELS)
        raise click.ClickException(
            f"Invalid model '{model}'. Valid models: {valid_models}"
        )

    rc = run_pipeline(
        yaml_file=yaml_file,
        model=model,
        max_workers=max_workers,
        max_budget=max_budget,
        timeout=timeout,
        dry_run=dry_run,
    )
    if rc != 0:
        raise click.exceptions.Exit(rc)


@cli.command()
@click.option(
    "--load-db",
    is_flag=True,
    default=False,
    help="Run sspsygene load-db on each deployed site.",
)
@click.option(
    "--no-push",
    is_flag=True,
    default=False,
    help="Skip the local git push step.",
)
@click.option(
    "--instances",
    type=str,
    default=None,
    help="Comma-separated subset of {dev, int, prod} to deploy to. Order in "
    "the list is ignored — instances are iterated in dev→int→prod order. "
    "Note: the three sites are independent (dev stages prod's public datasets; "
    "int is a parallel site for embargoed data) — this is not a staging chain. "
    "Default: all three.",
)
@click.option(
    "--build/--no-build",
    default=False,
    help="Run `npm install` + `npm run build` on each selected site. Default "
    "is off — wranglers running data/preprocess-only deploys never need this. "
    "Pass --build when JS/TS under web/ has changed. Implies --restart unless "
    "--no-restart is passed (the build mints a new Next.js build ID that "
    "invalidates the running service's served HTML).",
)
@click.option(
    "--restart/--no-restart",
    default=None,
    help="Restart web servers on psygene for the deployed instances after "
    "build/load-db (and before --run-tests, so e2e hits the new build). "
    "Default tracks --build: if you're building, you're restarting. Note "
    "the restart step uses kill-and-respawn against npm processes you own, "
    "so it only effectively bounces services whose systemd unit's User= "
    "matches the SSH'd user — currently `jbirgmei`. For other wranglers it "
    "silently no-ops; ask Johannes to restart, or `sudo systemctl restart "
    "sspsygene-dev` if you have sudo and don't mind the prompt.",
)
@click.option(
    "--preprocess",
    is_flag=True,
    default=False,
    help="Run each dataset's preprocess.py on every selected site before "
    "load-db. Independent of --load-db; running preprocess alone refreshes "
    "the processed CSVs without rebuilding the DB.",
)
@click.option(
    "--run-tests",
    is_flag=True,
    default=False,
    help="Run scripts/test.sh all on each selected site after build/load-db "
    "and (if --restart is set) restart, so the e2e tests hit the freshly "
    "deployed code. Includes slow tests (data-correspondence) and playwright "
    "e2e against the deployed URL. Hard-aborts on first failure.",
)
def deploy(
    load_db: bool,
    no_push: bool,
    instances: str | None,
    build: bool,
    restart: bool | None,
    preprocess: bool,
    run_tests: bool,
) -> None:
    """Deploy to production, dev, and internal sites on psygene."""
    from processing.deploy import run_deploy

    run_deploy(
        load_db=load_db,
        no_push=no_push,
        instances=instances,
        build=build,
        restart=restart,
        preprocess=preprocess,
        run_tests=run_tests,
    )


@cli.command(name="e2e-deployed")
@click.argument(
    "instance", type=click.Choice(["dev", "int", "prod"], case_sensitive=False)
)
def e2e_deployed(instance: str) -> None:
    """Run playwright e2e tests locally against a deployed instance.

    Sets E2E_BASE_URL to the instance's public URL and delegates to
    scripts/test.sh e2e — playwright drives browsers from web/node_modules
    against the deployed site. No ssh, no rebuild, no DB rebuild.
    """
    import os
    import subprocess

    from processing.deploy import INSTANCE_E2E_URLS

    base_url = INSTANCE_E2E_URLS[instance.lower()]
    # main.py is at <repo>/processing/src/processing/click/main.py
    repo_root = Path(__file__).resolve().parents[4]
    test_sh = repo_root / "scripts" / "test.sh"
    if not test_sh.is_file():
        raise click.ClickException(f"scripts/test.sh not found at {test_sh}")

    click.echo(f">>> e2e against {base_url}")
    env = {**os.environ, "E2E_BASE_URL": base_url}
    rc = subprocess.run([str(test_sh), "e2e"], env=env).returncode
    if rc != 0:
        raise click.exceptions.Exit(rc)


@cli.command(name="preprocess")
@click.option(
    "--dataset",
    type=str,
    default=None,
    help="Run only this dataset's preprocess.py (e.g. 'satterstrom-2020').",
)
@click.option(
    "--all",
    "run_all",
    is_flag=True,
    default=False,
    help="Run preprocess.py for every dataset that has one, not just those "
    "missing an in_path file.",
)
@click.option(
    "--max-workers",
    type=int,
    default=8,
    show_default=True,
    help="Number of preprocess.py scripts to run in parallel.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List which datasets would be preprocessed without running them.",
)
def preprocess(
    dataset: str | None,
    run_all: bool,
    max_workers: int,
    dry_run: bool,
) -> None:
    """Run dataset preprocess.py scripts locally to regenerate data files.

    The cleaned <table>.tsv/.csv outputs that in_path points at are gitignored
    and produced by preprocess.py from the raw download. After `sspsygene
    sync-data` pulls the raw inputs, this regenerates the cleaned outputs the
    server never persisted. Defaults to only datasets missing an in_path file.
    """
    from processing.preprocess_local import run_local_preprocess

    run_local_preprocess(
        dataset=dataset,
        run_all=run_all,
        dry_run=dry_run,
        max_workers=max_workers,
    )


@cli.command(name="sync-data")
@click.option(
    "--dataset",
    type=str,
    default=None,
    help="Sync only this dataset directory (e.g. 'satterstrom-2020'). "
    "Default: every local dataset directory.",
)
@click.option(
    "--instance",
    type=click.Choice(["dev", "int", "prod"], case_sensitive=False),
    default="dev",
    show_default=True,
    help="Reference instance to pull data files from. dev is effectively a "
    "superset of int and prod, so it's the right default.",
)
@click.option(
    "--host",
    type=str,
    default="hgwdev",
    show_default=True,
    help="SSH host used to read the instance's /hive tree. hgwdev is directly "
    "reachable and sees every instance's tree; pass 'psygene' to proxy-jump.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Also refresh files that already exist locally (rsync by size/mtime). "
    "Default is missing-files-only (never clobbers local edits).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be transferred without writing anything.",
)
def sync_data(
    dataset: str | None,
    instance: str,
    host: str,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Sync gitignored dataset data files from a reference instance (default: dev).

    Raw downloads and cleaned <table>.tsv outputs aren't in git, so a fresh
    checkout is missing the inputs load-db needs. This rsyncs the missing files
    down from dev without overwriting anything that already exists locally.
    """
    from processing.sync_data import run_sync_data

    run_sync_data(
        dataset=dataset,
        instance=instance.lower(),
        host=host,
        overwrite=overwrite,
        dry_run=dry_run,
    )


@cli.command(name="notify-wranglers")
@click.option(
    "--since",
    type=str,
    default=None,
    help="ISO date (YYYY-MM-DD) to look for changes from. "
    "Defaults to last notification date, or fails if no prior run.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("notify-output"),
    show_default=True,
    help="Directory to write email draft and doc suggestions.",
)
@click.option(
    "--timeout",
    type=int,
    default=300,
    show_default=True,
    help="Timeout in seconds per Claude agent.",
)
def notify_wranglers(since: str | None, output_dir: Path, timeout: int) -> None:
    """Draft a wrangler notification email and doc updates using Claude agents."""
    from processing.notify_wranglers import run_notify

    try:
        run_notify(since=since, output_dir=output_dir, timeout=timeout)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command(name="generate-llm-config")
@click.option(
    "--top-n",
    type=int,
    default=50,
    show_default=True,
    help="Number of top-ranked genes to include in the generated job file.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=str),
    default=None,
    help="Write YAML config to this file path. If omitted, print to stdout.",
)
def generate_llm_config(top_n: int, output: str | None) -> None:
    """Generate an LLM search YAML config from the database."""
    rc = generate_config(top_n=top_n, output=output)
    if rc != 0:
        raise click.exceptions.Exit(rc)
