import hashlib
import hmac
import json
import time
from time import sleep
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.observability.logging import runtime_logger


class BinanceRestError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        body: str,
        *,
        code: int | None = None,
        message: str | None = None,
        headers: Mapping[str, object] | None = None,
    ) -> None:
        detail = message or body
        super().__init__(f"Binance REST request failed: {status_code} {detail}")
        self.status_code = status_code
        self.body = body
        self.code = code
        self.message = message
        self.headers = dict(headers or {})


class BinanceRateLimitError(BinanceRestError):
    pass


class BinanceUnknownExecutionStatusError(BinanceRestError):
    pass


class BinanceNetworkError(RuntimeError):
    pass


class BinanceInvalidResponseError(RuntimeError):
    pass


def sign_params(params: Mapping[str, object], secret: str) -> dict[str, object]:
    signed_params = dict(params)
    query = urlencode(signed_params)
    signature = hmac.new(
        secret.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    signed_params["signature"] = signature
    return signed_params


def request_json(
    config: BinanceConfig,
    method: str,
    path: str,
    params: Mapping[str, object] | None = None,
    *,
    signed: bool = False,
    api_key_required: bool = False,
) -> object:
    attempts = max(1, config.retry_attempts)
    for attempt_index in range(attempts):
        runtime_logger.info(
            "binance rest request started",
            method=method.upper(),
            path=path,
            attempt=attempt_index + 1,
            attempts=attempts,
            signed=signed,
            api_key_required=api_key_required,
        )
        try:
            result = _request_json_once(
                config,
                method,
                path,
                params,
                signed=signed,
                api_key_required=api_key_required,
            )
            runtime_logger.info(
                "binance rest request succeeded",
                method=method.upper(),
                path=path,
                attempt=attempt_index + 1,
            )
            return result
        except (BinanceNetworkError, BinanceRateLimitError) as exc:
            if attempt_index == attempts - 1:
                runtime_logger.exception(
                    "binance rest request failed without retry",
                    method=method.upper(),
                    path=path,
                    attempt=attempt_index + 1,
                    error=str(exc),
                )
                raise
            delay = _retry_delay(config, exc)
            runtime_logger.warning(
                "binance rest request retry scheduled",
                method=method.upper(),
                path=path,
                attempt=attempt_index + 1,
                next_attempt=attempt_index + 2,
                delay_seconds=delay,
                error=str(exc),
            )
            sleep(delay)
    raise RuntimeError("unreachable Binance REST retry state")


def _request_json_once(
    config: BinanceConfig,
    method: str,
    path: str,
    params: Mapping[str, object] | None = None,
    *,
    signed: bool = False,
    api_key_required: bool = False,
) -> object:
    request_params = dict(params or {})
    headers: dict[str, str] = {}
    if signed or api_key_required:
        if not config.api_key:
            raise ValueError("Binance requests requiring API key need api_key")
        headers["X-MBX-APIKEY"] = config.api_key
    if signed:
        if not config.api_secret:
            raise ValueError("signed Binance requests require api_secret")
        request_params.setdefault("timestamp", _epoch_millis())
        request_params.setdefault("recvWindow", config.recv_window)
        request_params = sign_params(request_params, config.api_secret)

    query = urlencode(request_params)
    upper_method = method.upper()
    url = f"{config.base_url}{path}"
    data = None
    if upper_method == "GET" and query:
        url = f"{url}?{query}"
    elif query:
        data = query.encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = Request(url, data=data, headers=headers, method=upper_method)
    try:
        with urlopen(request, timeout=config.timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        runtime_logger.exception(
            "binance rest http error",
            method=upper_method,
            path=path,
            status_code=exc.code,
            body=body,
        )
        raise _classify_http_error(exc, body) from exc
    except URLError as exc:
        runtime_logger.exception(
            "binance rest network error",
            method=upper_method,
            path=path,
            error=str(exc.reason),
        )
        raise BinanceNetworkError(f"Binance REST network error: {exc.reason}") from exc

    if not body:
        runtime_logger.info("binance rest empty response", method=upper_method, path=path)
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        runtime_logger.exception(
            "binance rest invalid json",
            method=upper_method,
            path=path,
            body=body,
        )
        raise BinanceInvalidResponseError(
            f"Binance REST response was not valid JSON: {body}"
        ) from exc


def _retry_delay(config: BinanceConfig, exc: BaseException) -> float:
    if isinstance(exc, BinanceRateLimitError):
        retry_after = _header_value(exc.headers, "Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass
    return config.retry_delay


def _header_value(headers: Mapping[str, object], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return str(value)
    return None


def _epoch_millis() -> int:
    return int(time.time() * 1000)


def _classify_http_error(exc: HTTPError, body: str) -> BinanceRestError:
    error_payload = _parse_error_payload(body)
    code = _optional_int(error_payload.get("code"))
    message = _optional_str(error_payload.get("msg"))
    error_type: type[BinanceRestError]
    if exc.code in {418, 429}:
        error_type = BinanceRateLimitError
    elif exc.code == 503 and _is_unknown_execution_status(message or body):
        error_type = BinanceUnknownExecutionStatusError
    else:
        error_type = BinanceRestError
    return error_type(
        exc.code,
        body,
        code=code,
        message=message,
        headers=exc.headers,
    )


def _parse_error_payload(body: str) -> Mapping[str, object]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _is_unknown_execution_status(message: str) -> bool:
    normalized_message = message.lower()
    return (
        "unknown error" in normalized_message
        or "execution status unknown" in normalized_message
    )
