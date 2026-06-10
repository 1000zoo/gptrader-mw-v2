import asyncio
import inspect
import json
from decimal import Decimal
from typing import Awaitable, Callable, Mapping, Sequence, cast
from urllib.parse import urlparse

import websockets

from src.domain.position import PositionEvent
from src.domain.signal import SignalDirection
from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.infrastructure.exchange.binance.binance_rest import request_json


PositionEventHandler = Callable[[PositionEvent], object | Awaitable[object]]
Connect = Callable[[str], object]
Sleep = Callable[[float], Awaitable[object]]


class BinanceUserDataStreamRuntime:
    def __init__(
        self,
        config: BinanceConfig | None = None,
        *,
        connect: Connect | None = None,
        sleep: Sleep | None = None,
        reconnect_delay: float = 1.0,
        keepalive_interval: float = 30 * 60,
    ) -> None:
        self._config = config or BinanceConfig.from_env()
        self._connect = connect or websockets.connect
        self._sleep = sleep or asyncio.sleep
        self._reconnect_delay = reconnect_delay
        self._keepalive_interval = keepalive_interval

    async def consume(
        self,
        handler: PositionEventHandler,
        *,
        max_reconnects: int | None = None,
    ) -> None:
        reconnects = 0
        while True:
            listen_key = start_user_data_stream_api(self._config)
            keepalive_task = asyncio.create_task(self._keepalive_loop(listen_key))
            try:
                await self._consume_once(listen_key, handler)
                return
            except Exception:
                if max_reconnects is not None and reconnects >= max_reconnects:
                    raise
                reconnects += 1
                await self._sleep(self._reconnect_delay)
            finally:
                keepalive_task.cancel()
                await _ignore_cancelled(keepalive_task)
                close_user_data_stream_api(self._config, listen_key)

    async def _consume_once(
        self,
        listen_key: str,
        handler: PositionEventHandler,
    ) -> None:
        async with self._connect(build_user_data_stream_url(self._config, listen_key)) as stream:
            async for message in stream:
                payload = json.loads(message)
                for event in map_user_data_stream_position_events(payload):
                    await _call_handler(handler, event)

    async def _keepalive_loop(self, listen_key: str) -> None:
        while True:
            await self._sleep(self._keepalive_interval)
            keepalive_user_data_stream_api(self._config, listen_key)


def start_user_data_stream_api(config: BinanceConfig) -> str:
    payload = cast(
        Mapping[str, object],
        request_json(
            config,
            "POST",
            "/fapi/v1/listenKey",
            api_key_required=True,
        ),
    )
    listen_key = payload.get("listenKey")
    if not isinstance(listen_key, str) or not listen_key:
        raise ValueError("Binance listenKey response is missing listenKey")
    return listen_key


def keepalive_user_data_stream_api(config: BinanceConfig, listen_key: str) -> None:
    request_json(
        config,
        "PUT",
        "/fapi/v1/listenKey",
        params={"listenKey": listen_key},
        api_key_required=True,
    )


def close_user_data_stream_api(config: BinanceConfig, listen_key: str) -> None:
    request_json(
        config,
        "DELETE",
        "/fapi/v1/listenKey",
        params={"listenKey": listen_key},
        api_key_required=True,
    )


def build_user_data_stream_url(config: BinanceConfig, listen_key: str) -> str:
    parsed = urlparse(config.base_url)
    if parsed.netloc == "fapi.binance.com":
        return f"wss://fstream.binance.com/ws/{listen_key}"
    if parsed.netloc == "testnet.binancefuture.com":
        return f"wss://stream.binancefuture.com/ws/{listen_key}"
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/ws/{listen_key}"


def map_user_data_stream_position_events(
    payload: Mapping[str, object],
) -> tuple[PositionEvent, ...]:
    if payload.get("e") != "ORDER_TRADE_UPDATE":
        return ()
    order = payload.get("o")
    if not isinstance(order, Mapping):
        return ()
    if order.get("x") != "TRADE" or order.get("X") != "FILLED":
        return ()

    quantity = _decimal_field(order, "l")
    price = _decimal_field(order, "L")
    side = _str_field(order, "S")
    position_side = _str_field(order, "ps")
    if quantity <= Decimal("0"):
        return ()

    event = _map_trade_event(side, position_side, quantity, price)
    return () if event is None else (event,)


def _map_trade_event(
    side: str,
    position_side: str,
    quantity: Decimal,
    price: Decimal,
) -> PositionEvent | None:
    if position_side == "LONG":
        if side == "BUY":
            return PositionEvent.increase(SignalDirection.LONG, quantity, price)
        if side == "SELL":
            return PositionEvent.decrease(quantity, price)
    if position_side == "SHORT":
        if side == "SELL":
            return PositionEvent.increase(SignalDirection.SHORT, quantity, price)
        if side == "BUY":
            return PositionEvent.decrease(quantity, price)
    if position_side == "BOTH":
        if side == "BUY":
            return PositionEvent.increase(SignalDirection.LONG, quantity, price)
        if side == "SELL":
            return PositionEvent.increase(SignalDirection.SHORT, quantity, price)
    return None


def _decimal_field(payload: Mapping[str, object], name: str) -> Decimal:
    value = payload.get(name)
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _str_field(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    return "" if value is None else str(value).upper()


async def _call_handler(
    handler: PositionEventHandler,
    event: PositionEvent,
) -> None:
    result = handler(event)
    if inspect.isawaitable(result):
        await result


async def _ignore_cancelled(task: asyncio.Task[object]) -> None:
    try:
        await task
    except asyncio.CancelledError:
        return
