from __future__ import annotations

import logging
from pathlib import Path
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator


_LEVEL = logging.INFO
_LOGGERS: dict[str, logging.Logger] = {}
_FORMATTER = logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s] %(message)s", "%H:%M:%S")
_FILE_PATH: Path | None = None
_STREAM_HANDLER: logging.Handler | None = None
_FILE_HANDLER: logging.Handler | None = None
_FILE_HANDLER_PATH: Path | None = None


def set_log_level(level: str) -> None:
    global _LEVEL
    _LEVEL = getattr(logging, level.upper(), logging.INFO)
    for logger in _LOGGERS.values():
        logger.setLevel(_LEVEL)


def configure_logging(*, level: str | None = None, file_path: str | None = None) -> None:
    global _FILE_PATH
    if level is not None:
        set_log_level(level)
    if file_path is not None:
        _FILE_PATH = Path(file_path).expanduser()
    _rebuild_handlers()
    for logger in _LOGGERS.values():
        _attach_handlers(logger)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if name not in _LOGGERS:
        _rebuild_handlers()
        _attach_handlers(logger)
    logger.setLevel(_LEVEL)
    _LOGGERS[name] = logger
    return logger


def _rebuild_handlers() -> None:
    global _STREAM_HANDLER, _FILE_HANDLER, _FILE_HANDLER_PATH
    if _STREAM_HANDLER is None:
        _STREAM_HANDLER = logging.StreamHandler()
        _STREAM_HANDLER.setFormatter(_FORMATTER)

    if _FILE_PATH is None:
        if _FILE_HANDLER is not None:
            try:
                _FILE_HANDLER.close()
            except Exception:  # noqa: BLE001
                pass
        _FILE_HANDLER = None
        _FILE_HANDLER_PATH = None
        return

    if _FILE_HANDLER is not None and _FILE_HANDLER_PATH == _FILE_PATH:
        return

    if _FILE_HANDLER is not None:
        try:
            _FILE_HANDLER.close()
        except Exception:  # noqa: BLE001
            pass
        _FILE_HANDLER = None

    _FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(_FILE_PATH, encoding="utf-8")
    file_handler.setFormatter(_FORMATTER)
    _FILE_HANDLER = file_handler
    _FILE_HANDLER_PATH = _FILE_PATH


def _attach_handlers(logger: logging.Logger) -> None:
    logger.handlers.clear()
    if _STREAM_HANDLER is not None:
        logger.addHandler(_STREAM_HANDLER)
    if _FILE_HANDLER is not None:
        logger.addHandler(_FILE_HANDLER)
    logger.propagate = False


class ConversationLocks:
    def __init__(self) -> None:
        self._locks = defaultdict(__import__("asyncio").Lock)

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        lock = self._locks[key]
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
