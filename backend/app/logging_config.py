"""Minimal logging setup used by the API process."""

import logging


def configure_logging(level: str) -> None:
    """Configure process logging without exposing application secrets."""
    normalized_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=normalized_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
