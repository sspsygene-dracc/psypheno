import logging
import sys
import shutil

import click

from processing.click.full_help_group import FullHelpGroup
from processing.config import get_sspsygene_config


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
def load_db(
    dataset: str | None,
    skip_missing_datasets: bool,
    no_index: bool,
    skip_gene_descriptions: bool,
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
            skip_missing=skip_missing_datasets,
            hgnc_path=config.gene_map_config.hgnc_file,
            no_index=no_index,
            data_dir=config.base_dir,
            skip_gene_descriptions=skip_gene_descriptions,
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


