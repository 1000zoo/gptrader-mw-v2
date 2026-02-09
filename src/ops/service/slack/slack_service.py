import asyncio
import json
from urllib import request

from loguru import logger

from src.ops.service.slack_setting.slack_setting_service import SlackSettingService


class SlackService:
    def __init__(self):
        self.setting_service = SlackSettingService()

    async def send_error_message(
        self,
        process_name: str,
        method: str,
        error_message: str,
        error_log: str,
    ) -> None:
        setting = await self.setting_service.find_active_by_process(process_name)
        if not setting or not setting.webhook_url:
            return

        payload = {
            "text": (
                ":rotating_light: Error detected\n"
                f"*Process*: {process_name}\n"
                f"*Method*: {method}\n"
                f"*Error*: {error_message}\n"
                f"*Channel*: {setting.channel_name or '-'}\n"
                f"*Traceback*:\n```{error_log}```"
            )
        }
        if setting.channel_name:
            payload["channel"] = setting.channel_name

        await asyncio.to_thread(self._post_webhook, setting.webhook_url, payload)

    def _post_webhook(self, webhook_url: str, payload: dict[str, str]) -> None:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=5) as resp:
                if resp.status >= 400:
                    logger.warning(f"slack send failed status={resp.status}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"slack send failed: {exc}")
