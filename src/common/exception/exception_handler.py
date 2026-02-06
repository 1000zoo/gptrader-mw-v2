import asyncio
import traceback

from loguru import logger

from src.ops.service.slack.slack_service import SlackService


def _format_traceback(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


async def handle_top_level_exception(
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
    )
    slack_service = SlackService()
    await slack_service.send_error_message(
        process_name=process_name,
        method=method,
        error_message=str(error),
        error_log=error_log,
    )


def handle_top_level_exception_sync(
    process_name: str,
    method: str,
    error: BaseException,
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(handle_top_level_exception(process_name, method, error))
    else:
        loop.create_task(handle_top_level_exception(process_name, method, error))
