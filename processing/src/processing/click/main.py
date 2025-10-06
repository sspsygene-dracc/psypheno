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
def load_db() -> None:
    """Load the database"""
    from processing.sq_load import load_db

    config = get_sspsygene_config()
    config.out_db.parent.mkdir(parents=True, exist_ok=True)
    load_db(config.out_db, config.tables_config.tables)
