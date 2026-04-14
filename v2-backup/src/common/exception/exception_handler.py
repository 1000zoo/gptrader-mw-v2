import asyncio
import traceback

from loguru import logger


def _format_traceback(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def handle_top_level_exception(
    process_name: str,
    method: str,
    error: BaseException,
) -> None:
    error_log = _format_traceback(error)
    logger.error(
        "Top-level exception occurred: process=%s method=%s error=%s",
        process_name,
        method,
        error,
        error_log
    )


def handle_top_level_exception_sync(
    process_name: str,
    method: str,
    error: BaseException,
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        handle_top_level_exception(process_name, method, error)
    else:
        handle_top_level_exception(process_name, method, error)
