import json
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.infrastructure.exchange.binance import binance_rest
from src.infrastructure.exchange.binance.binance_rest import (
    BinanceInvalidResponseError,
    BinanceNetworkError,
    BinanceRateLimitError,
    BinanceRestError,
    BinanceUnknownExecutionStatusError,
    request_json,
    sign_params,
)


class _Response:
    def __init__(self, body: str):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body.encode("utf-8")


def test_binance_config_default_uses_usdm_futures_base_url():
    config = BinanceConfig.default()

    assert config.base_url == "https://fapi.binance.com"
    assert config.api_key is None
    assert config.api_secret is None
    assert config.timeout == 10.0
    assert config.recv_window == 5000
    assert config.retry_attempts == 1
    assert config.retry_delay == 0.0


def test_binance_config_from_env_reads_credentials(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "api-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "api-secret")

    config = BinanceConfig.from_env()

    assert config.api_key == "api-key"
    assert config.api_secret == "api-secret"


def test_binance_config_from_env_selects_testnet_credentials_and_base_url(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET", "true")
    monkeypatch.setenv("BINANCE_API_KEY", "api-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "api-secret")
    monkeypatch.setenv("BINANCE_TEST_API_KEY", "test-api-key")
    monkeypatch.setenv("BINANCE_TEST_API_SECRET", "test-api-secret")

    config = BinanceConfig.from_env()

    assert config.base_url == "https://demo-fapi.binance.com"
    assert config.api_key == "test-api-key"
    assert config.api_secret == "test-api-secret"


def test_binance_config_base_url_override_is_used_for_live_mode(monkeypatch):
    monkeypatch.setenv("BINANCE_BASE_URL", "https://example.live")

    config = BinanceConfig.from_env()

    assert config.base_url == "https://example.live"


def test_binance_config_test_base_url_override_is_used_for_testnet(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET", "true")
    monkeypatch.setenv("BINANCE_BASE_URL", "https://example.live")
    monkeypatch.setenv("BINANCE_TEST_BASE_URL", "https://example.test")

    config = BinanceConfig.from_env()

    assert config.base_url == "https://example.test"


def test_sign_params_appends_stable_hmac_sha256_signature():
    signed = sign_params(
        {"symbol": "BTCUSDT", "timestamp": 1499827319559},
        "secret-key",
    )

    assert signed == {
        "symbol": "BTCUSDT",
        "timestamp": 1499827319559,
        "signature": "e41ad55de6aa4880b4a3c5b1b85b3dcadba0f8210b576ec7f3e6b1813fba1872",
    }


def test_request_json_builds_unsigned_get_query(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response('{"ok": true}')

    monkeypatch.setattr(binance_rest, "urlopen", fake_urlopen)

    result = request_json(
        BinanceConfig(base_url="https://api.test", timeout=3.5),
        "GET",
        "/fapi/v1/klines",
        params={"symbol": "BTCUSDT", "limit": 2},
    )

    request, timeout = requests[0]
    parsed = urlparse(request.full_url)
    assert result == {"ok": True}
    assert request.get_method() == "GET"
    assert parsed.scheme == "https"
    assert parsed.netloc == "api.test"
    assert parsed.path == "/fapi/v1/klines"
    assert parse_qs(parsed.query) == {"symbol": ["BTCUSDT"], "limit": ["2"]}
    assert request.data is None
    assert timeout == 3.5


def test_request_json_builds_signed_post_form(monkeypatch):
    requests = []
    monkeypatch.setattr(binance_rest, "_epoch_millis", lambda: 1499827319559)

    def fake_urlopen(request, timeout):
        requests.append(request)
        return _Response('{"orderId": 123}')

    monkeypatch.setattr(binance_rest, "urlopen", fake_urlopen)

    result = request_json(
        BinanceConfig(
            api_key="api-key",
            api_secret="secret-key",
            base_url="https://api.test",
            recv_window=6000,
        ),
        "POST",
        "/fapi/v1/order",
        params={"symbol": "BTCUSDT", "reduceOnly": "true"},
        signed=True,
    )

    request = requests[0]
    body = parse_qs(request.data.decode("utf-8"))
    assert result == {"orderId": 123}
    assert request.full_url == "https://api.test/fapi/v1/order"
    assert request.get_method() == "POST"
    assert request.headers["X-mbx-apikey"] == "api-key"
    assert request.headers["Content-type"] == "application/x-www-form-urlencoded"
    assert body["symbol"] == ["BTCUSDT"]
    assert body["reduceOnly"] == ["true"]
    assert body["timestamp"] == ["1499827319559"]
    assert body["recvWindow"] == ["6000"]
    assert "signature" in body


def test_request_json_builds_api_key_only_request(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return _Response('{"listenKey": "listen-key"}')

    monkeypatch.setattr(binance_rest, "urlopen", fake_urlopen)

    result = request_json(
        BinanceConfig(api_key="api-key", base_url="https://api.test"),
        "POST",
        "/fapi/v1/listenKey",
        api_key_required=True,
    )

    request = requests[0]
    assert result == {"listenKey": "listen-key"}
    assert request.full_url == "https://api.test/fapi/v1/listenKey"
    assert request.headers["X-mbx-apikey"] == "api-key"
    assert request.data is None


def test_request_json_retries_network_errors(monkeypatch):
    attempts = []
    sleeps = []

    def fake_urlopen(request, timeout):
        attempts.append(request)
        if len(attempts) == 1:
            raise URLError("temporary reset")
        return _Response('{"ok": true}')

    monkeypatch.setattr(binance_rest, "urlopen", fake_urlopen)
    monkeypatch.setattr(binance_rest, "sleep", lambda seconds: sleeps.append(seconds))

    result = request_json(
        BinanceConfig(base_url="https://api.test", retry_attempts=2, retry_delay=0.25),
        "GET",
        "/fapi/v1/time",
    )

    assert result == {"ok": True}
    assert len(attempts) == 2
    assert sleeps == [0.25]


def test_request_json_retries_rate_limit_errors_with_retry_after(monkeypatch):
    attempts = []
    sleeps = []

    def fake_urlopen(request, timeout):
        attempts.append(request)
        if len(attempts) == 1:
            raise HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "2"},
                BytesIO(b'{"code": -1003, "msg": "Too many requests"}'),
            )
        return _Response('{"ok": true}')

    monkeypatch.setattr(binance_rest, "urlopen", fake_urlopen)
    monkeypatch.setattr(binance_rest, "sleep", lambda seconds: sleeps.append(seconds))

    result = request_json(
        BinanceConfig(base_url="https://api.test", retry_attempts=2, retry_delay=0.25),
        "GET",
        "/fapi/v1/time",
    )

    assert result == {"ok": True}
    assert len(attempts) == 2
    assert sleeps == [2.0]


def test_request_json_classifies_rate_limit_errors(monkeypatch):
    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {},
            BytesIO(b'{"code": -1003, "msg": "Too many requests"}'),
        )

    monkeypatch.setattr(binance_rest, "urlopen", fake_urlopen)

    with pytest.raises(BinanceRateLimitError) as exc_info:
        request_json(BinanceConfig(base_url="https://api.test"), "GET", "/fapi/v1/time")

    assert exc_info.value.status_code == 429
    assert exc_info.value.code == -1003
    assert exc_info.value.message == "Too many requests"


def test_request_json_classifies_unknown_execution_status(monkeypatch):
    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            503,
            "Service Unavailable",
            {},
            BytesIO(
                json.dumps(
                    {
                        "code": -1000,
                        "msg": "Unknown error, please check your request or try again later.",
                    }
                ).encode("utf-8")
            ),
        )

    monkeypatch.setattr(binance_rest, "urlopen", fake_urlopen)

    with pytest.raises(BinanceUnknownExecutionStatusError):
        request_json(
            BinanceConfig(base_url="https://api.test"),
            "POST",
            "/fapi/v1/order",
            params={"symbol": "BTCUSDT"},
        )


def test_request_json_wraps_network_errors(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("timed out")

    monkeypatch.setattr(binance_rest, "urlopen", fake_urlopen)

    with pytest.raises(BinanceNetworkError) as exc_info:
        request_json(BinanceConfig(base_url="https://api.test"), "GET", "/fapi/v1/time")

    assert "timed out" in str(exc_info.value)


def test_request_json_wraps_invalid_json(monkeypatch):
    monkeypatch.setattr(binance_rest, "urlopen", lambda request, timeout: _Response("{"))

    with pytest.raises(BinanceInvalidResponseError):
        request_json(BinanceConfig(base_url="https://api.test"), "GET", "/fapi/v1/time")
