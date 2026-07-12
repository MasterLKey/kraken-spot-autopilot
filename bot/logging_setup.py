from __future__ import annotations

import logging
import sys
from typing import Optional

from rich.logging import RichHandler


def setup_logging(level: str = "INFO") -> logging.Logger:
    root = logging.getLogger()
    if root.handlers:
        for handler in list(root.handlers):
            root.removeHandler(handler)

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False, markup=False)],
    )
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return logging.getLogger("bot")


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(name or "bot")
