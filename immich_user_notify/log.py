"""Logging setup. Kept tiny on purpose: one stdout handler, level from config."""

from __future__ import annotations

import logging
import sys


def resolve_level(level: str) -> int:
    """Map a level name to its int value; unknown/typo'd names fall back to INFO
    (getattr(logging, name) could otherwise return a non-level module attribute)."""
    return logging.getLevelNamesMapping().get((level or "").upper(), logging.INFO)


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging to stdout. Safe to call once at startup.

    The container's TZ env var drives the local time used in timestamps.
    """
    logging.basicConfig(
        level=resolve_level(level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )
