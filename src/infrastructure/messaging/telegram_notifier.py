from collections.abc import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.infrastructure.messaging.operational_message import (
    NotificationResult,
    OperationalMessage,
)


HttpOpen = Callable[[Request, float], object]


class TelegramNotifier:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        opener: HttpOpen | None = None,
        api_base_url: str = "https://api.telegram.org",
        timeout: float = 10.0,
        raise_on_error: bool = False,
    ) -> None:
        bot_token = bot_token.strip()
        chat_id = chat_id.strip()
        if not bot_token:
            raise ValueError("bot_token is required")
        if not chat_id:
            raise ValueError("chat_id is required")
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._opener = opener or urlopen
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout = timeout
        self._raise_on_error = raise_on_error

    def notify(self, message: OperationalMessage) -> NotificationResult:
        data = urlencode(
            {
                "chat_id": self._chat_id,
                "text": message.format_text(),
            }
        ).encode("utf-8")
        request = Request(
            f"{self._api_base_url}/bot{self._bot_token}/sendMessage",
            data=data,
            method="POST",
        )
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            self._opener(request, self._timeout)
        except Exception as exc:
            if self._raise_on_error:
                raise
            return NotificationResult(
                delivered=False,
                provider="telegram",
                destination=self._chat_id,
                error=exc,
            )
        return NotificationResult(
            delivered=True,
            provider="telegram",
            destination=self._chat_id,
        )
