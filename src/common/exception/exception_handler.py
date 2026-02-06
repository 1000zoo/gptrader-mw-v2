import traceback

from loguru import logger

from src.slack.service.slack_message.slack_message_service import SlackMessageService


async def handle_top_level_exception(process_name: str, method: str, error: Exception) -> None:
    error_type = type(error).__name__
    error_message = str(error)
    error_log = traceback.format_exc()
    logger.exception(
        f"Top-level exception captured. process={process_name} "
        f"method={method} error={error_message}"
    )

    try:
        service = SlackMessageService()
        await service.send_error_message(
            process_name=process_name,
            method=method,
            error_type=error_type,
            error_message=error_message,
            error_log=error_log,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Slack error handler failed: {exc}")
