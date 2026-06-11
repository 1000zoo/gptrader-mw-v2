from urllib.parse import parse_qs

from src.infrastructure.messaging import OperationalMessage, TelegramNotifier


class FakeResponse:
    pass


def test_telegram_notifier_posts_form_encoded_message() -> None:
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    notifier = TelegramNotifier(
        bot_token="token",
        chat_id="chat",
        opener=opener,
        api_base_url="https://telegram.test",
        timeout=3.0,
    )

    result = notifier.notify(OperationalMessage(title="Stream", body="connected"))

    request, timeout = calls[0]
    body = parse_qs(request.data.decode("utf-8"))
    assert result.delivered is True
    assert request.full_url == "https://telegram.test/bottoken/sendMessage"
    assert timeout == 3.0
    assert body["chat_id"] == ["chat"]
    assert "Stream" in body["text"][0]


def test_telegram_notifier_isolates_delivery_failure() -> None:
    error = RuntimeError("telegram unavailable")

    def opener(request, timeout):
        raise error

    notifier = TelegramNotifier(bot_token="token", chat_id="chat", opener=opener)

    result = notifier.notify(OperationalMessage(title="Stream", body="failed"))

    assert result.delivered is False
    assert result.error is error
