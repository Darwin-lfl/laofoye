from __future__ import annotations

import logging

from utils import configure_logging, get_logger, set_log_level


def test_set_log_level_updates_existing_loggers():
    logger = get_logger("test.logging.level.update")
    set_log_level("warning")
    assert logger.level == logging.WARNING

    set_log_level("debug")
    assert logger.level == logging.DEBUG


def test_configure_logging_writes_to_file(tmp_path):
    log_file = tmp_path / "logs" / "app.log"
    configure_logging(level="info", file_path=str(log_file))
    logger = get_logger("test.logging.file")
    logger.info("hello file logger")

    for handler in logger.handlers:
        handler.flush()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "hello file logger" in content


def test_configure_logging_applies_to_existing_logger(tmp_path):
    logger = get_logger("test.logging.reconfigure")
    log_file = tmp_path / "reconfigured.log"
    configure_logging(file_path=str(log_file))
    logger.info("existing logger writes file")
    for handler in logger.handlers:
        handler.flush()
    assert "existing logger writes file" in log_file.read_text(encoding="utf-8")
