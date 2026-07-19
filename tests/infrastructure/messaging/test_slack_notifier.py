from src.infrastructure.messaging import OperationalMessage, SlackNotifier


class FakeSlackClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, str]] = []

    def chat_postMessage(self, *, channel: str, text: str) -> object:
        self.calls.append({"channel": channel, "text": text})
        if self.error is not None:
            raise self.error
        return {"ok": True}


def test_slack_notifier_posts_formatted_message() -> None:
    client = FakeSlackClient()
    notifier = SlackNotifier(client, channel="#ops")

    result = notifier.notify(OperationalMessage(title="Order filled", body="BTCUSDT"))

    assert result.delivered is True
    assert result.provider == "slack"
    assert result.destination == "#ops"
    assert client.calls[0]["channel"] == "#ops"
    assert "Order filled" in client.calls[0]["text"]


def test_slack_notifier_isolates_delivery_failure() -> None:
    error = RuntimeError("slack unavailable")
    notifier = SlackNotifier(FakeSlackClient(error=error), channel="#ops")

    result = notifier.notify(OperationalMessage(title="Order filled", body="BTCUSDT"))

    assert result.delivered is False
    assert result.failed is True
    assert result.error is error
