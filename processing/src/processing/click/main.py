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
    "the list is ignored — deployment always rolls dev → int → prod. "
    "Default: all three.",
)
@click.option(
    "--restart",
    is_flag=True,
    default=False,
    help="Restart web servers on psygene for the deployed instances after "
    "build/load-db (and before --run-tests, so e2e hits the new build). "
    "Default is no restart — the web process auto-detects DB changes (see "
    "web/lib/db.ts), so DB-only deploys do not need this. Pass it whenever "
    "JS code has changed.",
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
    restart: bool,
    preprocess: bool,
    run_tests: bool,
) -> None:
    """Deploy to production, dev, and internal sites on psygene."""
    from processing.deploy import run_deploy

    run_deploy(
        load_db=load_db,
        no_push=no_push,
        instances=instances,
        restart=restart,
        preprocess=preprocess,
        run_tests=run_tests,
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
