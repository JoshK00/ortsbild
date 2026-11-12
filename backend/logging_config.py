import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DEFAULT_LOG_DIR = Path(__file__).resolve().parent / "logs"
LOGGER_NAME = "ortsbild"  # all our loggers (ortsbild.privacy, ...) are children of it


def setup_logging(level: str | None = None, log_dir: Path = DEFAULT_LOG_DIR) -> None:
    """Send the logs of our code to the terminal and to backend/logs/ortsbild.log.

    The level comes from the argument, else from the environment variable LOG_LEVEL, else INFO.
    The file rotates (5 MB, 3 old files are kept). The log never contains raw data, only
    report ids, step names and error types. Calling this twice does not add handlers twice.

    TODO: Send the log to a safe central place with alerts once the backend is hosted.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel((level or os.getenv("LOG_LEVEL", "INFO")).upper())
    if logger.handlers:
        return
    formatter = logging.Formatter(LOG_FORMAT)
    log_dir.mkdir(parents=True, exist_ok=True)
    for handler in (
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(log_dir / "ortsbild.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"),
    ):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.propagate = False  # otherwise a parent handler would print every line twice
