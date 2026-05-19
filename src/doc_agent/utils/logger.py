"""Rich-backed logger with one shared handler per process."""

import logging

from rich.logging import RichHandler

from doc_agent.config import settings


def get_logger(name: str = "doc-agent") -> logging.Logger:
    """Return a configured logger. Safe to call repeatedly — handlers are not duplicated."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level = settings.log_level
    logger.setLevel(level)
    handler = RichHandler(
        rich_tracebacks=True,
        show_time=True,
        show_path=False,
        markup=True,
    )
    handler.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
