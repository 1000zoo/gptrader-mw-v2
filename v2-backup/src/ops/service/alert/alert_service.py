import json
import os
from urllib import request

from loguru import logger


class AlertService:
    def __init__(self):
        self.slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    def send_slack_alert(self, message: str) -> None:
        if not self.slack_webhook_url:
            return
        payload = json.dumps({"text": message}).encode("utf-8")
        req = request.Request(
            self.slack_webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=5) as resp:
                if resp.status >= 400:
                    logger.warning(f"slack alert failed status={resp.status}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"slack alert failed: {exc}")
