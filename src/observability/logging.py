import logging
import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any


try:
    from loguru import logger as _loguru_logger
except ModuleNotFoundError:
    _loguru_logger = None


_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} | "
    "{message} | {extra}"
)
_STD_LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
)
_configured = False


class RuntimeLogger:
    def __init__(self) -> None:
        self._stdlib_logger = logging.getLogger("gptrader.runtime")

    def configure(
        self,
        *,
        log_root: str | Path = "logs",
        current_date: date | None = None,
        level: str = "INFO",
    ) -> Path:
        log_date = current_date or datetime.now().date()
        log_dir = Path(log_root) / log_date.isoformat()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "runtime.log"

        global _configured
        if _loguru_logger is not None:
            _loguru_logger.remove()
            _loguru_logger.add(
                sys.stderr,
                level=level,
                format=_LOG_FORMAT,
                backtrace=True,
                diagnose=False,
            )
            _loguru_logger.add(
                log_file,
                level=level,
                format=_LOG_FORMAT,
                encoding="utf-8",
                backtrace=True,
                diagnose=False,
            )
        else:
            self._configure_stdlib_logger(log_file=log_file, level=level)

        _configured = True
        return log_file

    def info(self, message: str, **context: Any) -> None:
        if _loguru_logger is not None:
            _loguru_logger.bind(**context).info(message)
            return
        self._stdlib_logger.info(_format_message(message, context))

    def warning(self, message: str, **context: Any) -> None:
        if _loguru_logger is not None:
            _loguru_logger.bind(**context).warning(message)
            return
        self._stdlib_logger.warning(_format_message(message, context))

    def error(self, message: str, **context: Any) -> None:
        if _loguru_logger is not None:
            _loguru_logger.bind(**context).error(message)
            return
        self._stdlib_logger.error(_format_message(message, context))

    def exception(self, message: str, **context: Any) -> None:
        if _loguru_logger is not None:
            _loguru_logger.bind(**context).exception(message)
            return
        self._stdlib_logger.error(
            f"{_format_message(message, context)}\n{traceback.format_exc()}"
        )

    def _configure_stdlib_logger(self, *, log_file: Path, level: str) -> None:
        self._stdlib_logger.handlers.clear()
        self._stdlib_logger.setLevel(level)
        self._stdlib_logger.propagate = False

        formatter = logging.Formatter(_STD_LOG_FORMAT)
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)

        self._stdlib_logger.addHandler(stream_handler)
        self._stdlib_logger.addHandler(file_handler)


runtime_logger = RuntimeLogger()


def configure_runtime_logging(
    *,
    log_root: str | Path = "logs",
    current_date: date | None = None,
    level: str = "INFO",
) -> Path:
    return runtime_logger.configure(
        log_root=log_root,
        current_date=current_date,
        level=level,
    )


def ensure_runtime_logging_configured() -> Path | None:
    if _configured:
        return None
    return configure_runtime_logging()


def _format_message(message: str, context: dict[str, Any]) -> str:
    if not context:
        return message
    return f"{message} | {context}"
