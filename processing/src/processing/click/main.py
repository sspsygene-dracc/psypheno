import logging
import sys
import shutil

import click

from processing.click.full_help_group import FullHelpGroup


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
