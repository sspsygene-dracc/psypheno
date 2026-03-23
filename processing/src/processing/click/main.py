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
    if log_file:
        logging.basicConfig(filename=log_file, level=log_level)
    else:
        logging.basicConfig(level=log_level, stream=sys.stdout)


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
def load_db(
    dataset: str | None,
    skip_missing_datasets: bool,
    no_index: bool,
    skip_gene_descriptions: bool,
    skip_meta_analysis: bool,
) -> None:
    """Load the database"""
    try:
        from processing.sq_load import load_db

        config = get_sspsygene_config(dataset=dataset)
        config.out_db.parent.mkdir(parents=True, exist_ok=True)
        load_db(
            config.out_db,
            config.tables_config.tables,
            assay_types=config.global_config.get("assayTypes", {}),
            disease_types=config.global_config.get("diseaseTypes", {}),
            skip_missing=skip_missing_datasets,
            hgnc_path=config.gene_map_config.hgnc_file,
            no_index=no_index,
            data_dir=config.base_dir,
            skip_gene_descriptions=skip_gene_descriptions,
            nimh_csv_path=config.gene_map_config.nimh_gene_list_file,
            tf_list_path=config.gene_map_config.tf_list_file,
            skip_meta_analysis=skip_meta_analysis,
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
    "--prod-only",
    is_flag=True,
    default=False,
    help="Deploy only the production site (skip internal).",
)
@click.option(
    "--int-only",
    is_flag=True,
    default=False,
    help="Deploy only the internal site (skip production).",
)
@click.option(
    "--no-restart",
    is_flag=True,
    default=False,
    help="Skip restarting web servers on psygene.",
)
def deploy(
    load_db: bool,
    no_push: bool,
    prod_only: bool,
    int_only: bool,
    no_restart: bool,
) -> None:
    """Deploy to production and internal sites on hgwdev/psygene."""
    from processing.deploy import run_deploy

    run_deploy(
        load_db=load_db,
        no_push=no_push,
        prod_only=prod_only,
        int_only=int_only,
        no_restart=no_restart,
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
