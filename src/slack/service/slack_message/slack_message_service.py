import asyncio
import json
from urllib import request

from loguru import logger

from src.slack.service.slack_setting.slack_setting_service import SlackSettingService


class SlackMessageService:
    def __init__(self):
        self.setting_service = SlackSettingService()

    async def send_error_message(
        self,
        process_name: str,
        method: str,
        error_type: str,
        error_message: str,
        error_log: str,
    ) -> None:
        setting = await self.setting_service.find_active_by_process(process_name)
        if not setting or not setting.webhook_url:
            logger.warning(f"Slack setting missing for process={process_name}")
            return

        message = self._format_error_message(
            process_name=process_name,
            method=method,
            error_type=error_type,
            error_message=error_message,
            error_log=error_log,
        )

        await asyncio.to_thread(self._post_webhook, setting.webhook_url, message)

    def _format_error_message(
        self,
        process_name: str,
        method: str,
        error_type: str,
        error_message: str,
        error_log: str,
    ) -> str:
        return (
            "[ERROR]\n"
            f"process: {process_name}\n"
            f"method: {method}\n"
            f"error: {error_type}: {error_message}\n"
            f"log:\n{error_log}"
        )

    def _post_webhook(self, webhook_url: str, message: str) -> None:
        payload = json.dumps({"text": message}).encode("utf-8")
        req = request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=5) as resp:
                if resp.status >= 400:
                    logger.warning(f"slack message failed status={resp.status}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"slack message failed: {exc}")
