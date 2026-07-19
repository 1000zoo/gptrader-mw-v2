"""Manual Binance API test app.

Run from the repository root:
    uvicorn api_test.binance_api_test_app:app --reload --port 8010

Swagger UI:
    http://127.0.0.1:8010/docs
"""

from pathlib import Path
from typing import Any, Literal, Mapping

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from src.infrastructure.exchange.binance.account.binance_account_adapter import (
    load_account_api,
)
from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.infrastructure.exchange.binance.binance_rest import (
    BinanceInvalidResponseError,
    BinanceNetworkError,
    BinanceRestError,
    request_json,
)
from src.infrastructure.exchange.binance.market_data.binance_market_data_adapter import (
    load_klines_api,
)
from src.infrastructure.exchange.binance.order_execution.binance_order_execution_adapter import (
    load_orders_api,
    submit_order_api,
)
from src.infrastructure.exchange.binance.position_stream import (
    build_user_data_stream_url,
    close_user_data_stream_api,
    keepalive_user_data_stream_api,
    start_user_data_stream_api,
)

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.test")

app = FastAPI(
    title="Binance API Manual Test",
    description="Manual Binance request/response inspection endpoints for Postman.",
)


class OrderParamsRequest(BaseModel):
    symbol: str = Field(default="BTCUSDT")
    side: Literal["BUY", "SELL"] = Field(default="BUY")
    type: Literal["MARKET", "LIMIT"] = Field(default="MARKET")
    quantity: str = Field(default="0.001")
    newClientOrderId: str | None = Field(default=None)
    price: str | None = Field(default=None)
    timeInForce: str | None = Field(default=None)
    reduceOnly: bool | None = Field(default=None)
    extra_params: dict[str, Any] = Field(default_factory=dict)

    def to_binance_params(self) -> dict[str, object]:
        params: dict[str, object] = {
            "symbol": self.symbol,
            "side": self.side,
            "type": self.type,
            "quantity": self.quantity,
        }
        if self.newClientOrderId:
            params["newClientOrderId"] = self.newClientOrderId
        if self.price is not None:
            params["price"] = self.price
        if self.timeInForce is not None:
            params["timeInForce"] = self.timeInForce
        elif self.type == "LIMIT":
            params["timeInForce"] = "GTC"
        if self.reduceOnly is not None:
            params["reduceOnly"] = "true" if self.reduceOnly else "false"
        params.update(self.extra_params)
        return params


class RawRequest(BaseModel):
    method: Literal["GET", "POST", "PUT", "DELETE"]
    path: str
    params: dict[str, Any] = Field(default_factory=dict)
    signed: bool = False
    api_key_required: bool = False


def _config() -> BinanceConfig:
    return BinanceConfig.from_env()


def _config_snapshot(config: BinanceConfig) -> dict[str, object]:
    return {
        "base_url": config.base_url,
        "timeout": config.timeout,
        "recv_window": config.recv_window,
        "retry_attempts": config.retry_attempts,
        "retry_delay": config.retry_delay,
        "has_api_key": bool(config.api_key),
        "has_api_secret": bool(config.api_secret),
    }


def _ok(
    *,
    operation: str,
    request: Mapping[str, object],
    response: object,
) -> dict[str, object]:
    return {
        "ok": True,
        "operation": operation,
        "config": _config_snapshot(_config()),
        "request": dict(request),
        "response": response,
    }


def _raise_api_error(exc: Exception) -> None:
    if isinstance(exc, BinanceRestError):
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error_type": type(exc).__name__,
                "message": str(exc),
                "binance_code": exc.code,
                "binance_message": exc.message,
                "binance_body": exc.body,
                "binance_headers": exc.headers,
            },
        ) from exc
    if isinstance(exc, (BinanceNetworkError, BinanceInvalidResponseError, ValueError)):
        raise HTTPException(
            status_code=502,
            detail={
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        ) from exc
    raise exc


@app.get("/health")
def health() -> dict[str, object]:
    config = _config()
    return {
        "ok": True,
        "config": _config_snapshot(config),
    }


@app.get("/binance/time")
def binance_time() -> dict[str, object]:
    config = _config()
    request = {"method": "GET", "path": "/fapi/v1/time", "params": {}}
    try:
        response = request_json(config, "GET", "/fapi/v1/time")
    except Exception as exc:
        _raise_api_error(exc)
    return _ok(operation="time", request=request, response=response)


@app.get("/binance/klines")
def binance_klines(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="1m"),
    limit: int = Query(default=5, ge=1, le=1500),
) -> dict[str, object]:
    config = _config()
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        response = load_klines_api(config, symbol=symbol, interval=interval, limit=limit)
    except Exception as exc:
        _raise_api_error(exc)
    return _ok(
        operation="klines",
        request={"method": "GET", "path": "/fapi/v1/klines", "params": params},
        response=response,
    )


@app.get("/binance/account")
def binance_account() -> dict[str, object]:
    config = _config()
    request = {
        "method": "GET",
        "path": "/fapi/v2/account",
        "params": {"timestamp": "<auto>", "recvWindow": config.recv_window},
        "signed": True,
    }
    try:
        response = load_account_api(config)
    except Exception as exc:
        _raise_api_error(exc)
    return _ok(operation="account", request=request, response=response)


@app.get("/binance/orders")
def binance_orders(
    symbol: str = Query(default="BTCUSDT"),
    start_time: int = Query(alias="startTime"),
    end_time: int = Query(alias="endTime"),
) -> dict[str, object]:
    config = _config()
    params = {"symbol": symbol, "startTime": start_time, "endTime": end_time}
    try:
        response = load_orders_api(
            config,
            symbol=symbol,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception as exc:
        _raise_api_error(exc)
    return _ok(
        operation="all_orders",
        request={
            "method": "GET",
            "path": "/fapi/v1/allOrders",
            "params": {**params, "timestamp": "<auto>", "recvWindow": config.recv_window},
            "signed": True,
        },
        response=response,
    )


@app.post("/binance/orders/payload")
def binance_order_payload(body: OrderParamsRequest) -> dict[str, object]:
    params = body.to_binance_params()
    return _ok(
        operation="order_payload",
        request={
            "method": "POST",
            "path": "/fapi/v1/order",
            "params": {**params, "timestamp": "<auto>", "recvWindow": _config().recv_window},
            "signed": True,
            "dry_run": True,
        },
        response={"binance_params": params},
    )


@app.post("/binance/orders/test")
def binance_order_test(body: OrderParamsRequest) -> dict[str, object]:
    config = _config()
    params = body.to_binance_params()
    try:
        response = request_json(
            config,
            "POST",
            "/fapi/v1/order/test",
            params=params,
            signed=True,
        )
    except Exception as exc:
        _raise_api_error(exc)
    return _ok(
        operation="order_test",
        request={
            "method": "POST",
            "path": "/fapi/v1/order/test",
            "params": {**params, "timestamp": "<auto>", "recvWindow": config.recv_window},
            "signed": True,
        },
        response=response,
    )


@app.post("/binance/orders/submit")
def binance_order_submit(
    body: OrderParamsRequest,
    confirm_live_order: bool = Query(default=False),
) -> dict[str, object]:
    if not confirm_live_order:
        raise HTTPException(
            status_code=400,
            detail="Set confirm_live_order=true to submit a real Binance order.",
        )
    config = _config()
    params = body.to_binance_params()
    try:
        response = submit_order_api(config, params)
    except Exception as exc:
        _raise_api_error(exc)
    return _ok(
        operation="order_submit",
        request={
            "method": "POST",
            "path": "/fapi/v1/order",
            "params": {**params, "timestamp": "<auto>", "recvWindow": config.recv_window},
            "signed": True,
            "confirm_live_order": True,
        },
        response=response,
    )


@app.post("/binance/listen-key")
def binance_listen_key_start() -> dict[str, object]:
    config = _config()
    try:
        listen_key = start_user_data_stream_api(config)
    except Exception as exc:
        _raise_api_error(exc)
    return _ok(
        operation="listen_key_start",
        request={
            "method": "POST",
            "path": "/fapi/v1/listenKey",
            "api_key_required": True,
        },
        response={
            "listenKey": listen_key,
            "websocket_url": build_user_data_stream_url(config, listen_key),
        },
    )


@app.put("/binance/listen-key/{listen_key}")
def binance_listen_key_keepalive(listen_key: str) -> dict[str, object]:
    config = _config()
    try:
        keepalive_user_data_stream_api(config, listen_key)
    except Exception as exc:
        _raise_api_error(exc)
    return _ok(
        operation="listen_key_keepalive",
        request={
            "method": "PUT",
            "path": "/fapi/v1/listenKey",
            "params": {"listenKey": listen_key},
            "api_key_required": True,
        },
        response={},
    )


@app.delete("/binance/listen-key/{listen_key}")
def binance_listen_key_close(listen_key: str) -> dict[str, object]:
    config = _config()
    try:
        close_user_data_stream_api(config, listen_key)
    except Exception as exc:
        _raise_api_error(exc)
    return _ok(
        operation="listen_key_close",
        request={
            "method": "DELETE",
            "path": "/fapi/v1/listenKey",
            "params": {"listenKey": listen_key},
            "api_key_required": True,
        },
        response={},
    )


@app.post("/binance/raw")
def binance_raw(body: RawRequest) -> dict[str, object]:
    config = _config()
    try:
        response = request_json(
            config,
            body.method,
            body.path,
            params=body.params,
            signed=body.signed,
            api_key_required=body.api_key_required,
        )
    except Exception as exc:
        _raise_api_error(exc)
    return _ok(
        operation="raw",
        request={
            "method": body.method,
            "path": body.path,
            "params": body.params,
            "signed": body.signed,
            "api_key_required": body.api_key_required,
        },
        response=response,
    )
