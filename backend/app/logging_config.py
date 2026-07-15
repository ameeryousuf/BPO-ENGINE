"""Application-wide logging configuration."""

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger once, at application startup."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
