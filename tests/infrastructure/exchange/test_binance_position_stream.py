import asyncio
import json
from decimal import Decimal

from src.domain.position import PositionEventType
from src.domain.signal import SignalDirection
from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.infrastructure.exchange.binance.position_stream import binance_position_stream
from src.infrastructure.exchange.binance.position_stream.binance_position_stream import (
    BinanceUserDataStreamRuntime,
    build_user_data_stream_url,
    close_user_data_stream_api,
    keepalive_user_data_stream_api,
    map_user_data_stream_position_events,
    start_user_data_stream_api,
)


class _FakeWebSocket:
    def __init__(self, messages):
        self._messages = list(messages)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        message = self._messages.pop(0)
        if isinstance(message, BaseException):
            raise message
        return message


def test_user_data_stream_api_functions_use_api_key_only_requests(monkeypatch):
    calls = []

    def fake_request_json(config, method, path, params=None, **kwargs):
        calls.append((config, method, path, params, kwargs))
        if method == "POST":
            return {"listenKey": "listen-key"}
        return {}

    monkeypatch.setattr(binance_position_stream, "request_json", fake_request_json)
    config = BinanceConfig(api_key="api-key", base_url="https://api.test")

    listen_key = start_user_data_stream_api(config)
    keepalive_user_data_stream_api(config, listen_key)
    close_user_data_stream_api(config, listen_key)

    assert listen_key == "listen-key"
    assert calls == [
        (config, "POST", "/fapi/v1/listenKey", None, {"api_key_required": True}),
        (
            config,
            "PUT",
            "/fapi/v1/listenKey",
            {"listenKey": "listen-key"},
            {"api_key_required": True},
        ),
        (
            config,
            "DELETE",
            "/fapi/v1/listenKey",
            {"listenKey": "listen-key"},
            {"api_key_required": True},
        ),
    ]


def test_map_order_trade_update_to_position_increase_event():
    payload = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "x": "TRADE",
            "X": "FILLED",
            "s": "BTCUSDT",
            "S": "BUY",
            "ps": "LONG",
            "l": "0.25",
            "L": "61000.50",
        },
    }

    events = map_user_data_stream_position_events(payload)

    assert len(events) == 1
    assert events[0].event_type is PositionEventType.INCREASE
    assert events[0].direction is SignalDirection.LONG
    assert events[0].quantity == Decimal("0.25")
    assert events[0].price == Decimal("61000.50")


def test_runtime_connects_to_user_data_stream_and_emits_position_events(monkeypatch):
    started = []
    closed = []
    connected_urls = []

    monkeypatch.setattr(
        binance_position_stream,
        "start_user_data_stream_api",
        lambda config: started.append(config) or "listen-key",
    )
    monkeypatch.setattr(
        binance_position_stream,
        "close_user_data_stream_api",
        lambda config, listen_key: closed.append((config, listen_key)),
    )

    payload = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "x": "TRADE",
            "X": "FILLED",
            "s": "BTCUSDT",
            "S": "SELL",
            "ps": "LONG",
            "l": "0.10",
            "L": "62000",
        },
    }

    def fake_connect(url):
        connected_urls.append(url)
        return _FakeWebSocket([json.dumps(payload)])

    received = []
    config = BinanceConfig(api_key="api-key", base_url="https://api.test")
    runtime = BinanceUserDataStreamRuntime(config, connect=fake_connect)

    asyncio.run(runtime.consume(received.append))

    assert started == [config]
    assert connected_urls == [build_user_data_stream_url(config, "listen-key")]
    assert closed == [(config, "listen-key")]
    assert received[0].event_type is PositionEventType.DECREASE
    assert received[0].quantity == Decimal("0.10")


def test_runtime_reconnects_after_connection_failure(monkeypatch):
    connect_attempts = []
    sleeps = []

    monkeypatch.setattr(
        binance_position_stream,
        "start_user_data_stream_api",
        lambda config: "listen-key",
    )
    monkeypatch.setattr(
        binance_position_stream,
        "close_user_data_stream_api",
        lambda config, listen_key: None,
    )

    payload = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "x": "TRADE",
            "X": "FILLED",
            "s": "BTCUSDT",
            "S": "SELL",
            "ps": "SHORT",
            "l": "0.20",
            "L": "60000",
        },
    }

    def fake_connect(url):
        connect_attempts.append(url)
        if len(connect_attempts) == 1:
            raise ConnectionError("socket reset")
        return _FakeWebSocket([json.dumps(payload)])

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    received = []
    runtime = BinanceUserDataStreamRuntime(
        BinanceConfig(api_key="api-key"),
        connect=fake_connect,
        sleep=fake_sleep,
        reconnect_delay=0.5,
    )

    asyncio.run(runtime.consume(received.append, max_reconnects=1))

    assert len(connect_attempts) == 2
    assert sleeps == [0.5]
    assert received[0].event_type is PositionEventType.INCREASE
    assert received[0].direction is SignalDirection.SHORT
