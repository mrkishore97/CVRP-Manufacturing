"""Minimal logging setup used by the API process."""

import logging


def configure_logging(level: str) -> None:
    """Configure process logging without exposing application secrets."""
    normalized_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=normalized_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # httpx logs request URLs at INFO; Google geocoding URLs contain the API key and
    # the raw address, so transport logging is limited to warnings and errors.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
