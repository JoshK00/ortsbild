import logging

import pytest

from logging_config import LOGGER_NAME, setup_logging


@pytest.fixture(autouse=True)
def clean_logger():
    """Each test starts and ends without handlers, so tests do not affect each other."""
    logger = logging.getLogger(LOGGER_NAME)
    yield logger
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger.propagate = True
    logger.setLevel(logging.NOTSET)


def test_log_lines_reach_the_file_and_the_terminal(tmp_path, capsys):
    """An error of a child logger is written to backend/logs and to the terminal."""
    setup_logging("INFO", log_dir=tmp_path)
    logging.getLogger("ortsbild.privacy").error("step blocked: report_id=7c9e")
    for handler in logging.getLogger(LOGGER_NAME).handlers:
        handler.flush()
    content = (tmp_path / "ortsbild.log").read_text()
    assert "ERROR ortsbild.privacy: step blocked: report_id=7c9e" in content
    assert "step blocked: report_id=7c9e" in capsys.readouterr().out


def test_setup_twice_does_not_duplicate_the_lines(tmp_path):
    """Calling setup_logging again (e.g. on a reload) must not print every line twice."""
    setup_logging("INFO", log_dir=tmp_path)
    setup_logging("INFO", log_dir=tmp_path)
    assert len(logging.getLogger(LOGGER_NAME).handlers) == 2  # terminal and file


def test_level_comes_from_the_environment(tmp_path, monkeypatch):
    """LOG_LEVEL=WARNING hides info lines."""
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    setup_logging(log_dir=tmp_path)
    assert logging.getLogger(LOGGER_NAME).level == logging.WARNING
