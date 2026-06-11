from typing import Protocol

from src.infrastructure.messaging.operational_message import (
    NotificationResult,
    OperationalMessage,
)


class SlackClient(Protocol):
    def chat_postMessage(self, *, channel: str, text: str) -> object:
        ...


class SlackNotifier:
    def __init__(
        self,
        client: SlackClient,
        *,
        channel: str,
        raise_on_error: bool = False,
    ) -> None:
        channel = channel.strip()
        if not channel:
            raise ValueError("channel is required")
        self._client = client
        self._channel = channel
        self._raise_on_error = raise_on_error

    @classmethod
    def from_token(
        cls,
        token: str,
        *,
        channel: str,
        raise_on_error: bool = False,
    ) -> "SlackNotifier":
        from slack_sdk import WebClient

        return cls(
            WebClient(token=token),
            channel=channel,
            raise_on_error=raise_on_error,
        )

    def notify(self, message: OperationalMessage) -> NotificationResult:
        try:
            self._client.chat_postMessage(
                channel=self._channel,
                text=message.format_text(),
            )
        except Exception as exc:
            if self._raise_on_error:
                raise
            return NotificationResult(
                delivered=False,
                provider="slack",
                destination=self._channel,
                error=exc,
            )
        return NotificationResult(
            delivered=True,
            provider="slack",
            destination=self._channel,
        )
