from functools import cache
import logging


@cache
def get_sspsygene_logger() -> logging.Logger:
    rv = logging.getLogger("sspsygene_logger")
    return rv
