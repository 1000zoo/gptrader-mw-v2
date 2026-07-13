from datetime import datetime, timezone

from src.infrastructure.messaging import OperationalMessage, Severity


def test_operational_message_formats_text_and_payload() -> None:
    occurred_at = datetime(2026, 6, 11, 1, 2, 3, tzinfo=timezone.utc)
    message = OperationalMessage(
        title=" Stream stopped ",
        body=" reconnect failed ",
        severity=Severity.ERROR,
        source="websocket",
        occurred_at=occurred_at,
        metadata={"symbol": "BTCUSDT"},
    )

    text = message.format_text()
    payload = message.to_payload()

    assert "[ERROR] Stream stopped" in text
    assert "reconnect failed" in text
    assert "- symbol: BTCUSDT" in text
    assert payload == {
        "title": "Stream stopped",
        "body": "reconnect failed",
        "severity": "error",
        "source": "websocket",
        "occurred_at": "2026-06-11T01:02:03+00:00",
        "metadata": {"symbol": "BTCUSDT"},
    }
