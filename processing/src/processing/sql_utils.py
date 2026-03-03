import re


def sanitize_identifier(name: str) -> str:
    """Validate that a string is safe to use as a SQL identifier.

    Only allows alphanumeric characters and underscores (\\w+).
    Raises ValueError if the name contains any other characters.
    """
    if not re.match(r"^\w+$", name):
        raise ValueError(f"Invalid SQL identifier: {name}")
    return name
