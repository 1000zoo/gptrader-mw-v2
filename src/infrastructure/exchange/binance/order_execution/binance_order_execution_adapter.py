from datetime import datetime
from decimal import Decimal
from typing import Mapping, cast

from src.domain.execution import ExecutionReport, OrderRequest, OrderResult
from src.domain.market import Symbol
from src.domain.ports import OrderExecutionPort
from src.domain.signal import SignalDirection
from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.infrastructure.exchange.binance.binance_rest import request_json
from src.infrastructure.exchange.binance.order_execution.binance_order_execution_mapper import (
    map_binance_order_to_execution_report,
    map_binance_order_to_result,
    map_order_request_to_binance_params,
)


class BinanceOrderExecutionAdapter(OrderExecutionPort):
    def __init__(self, config: BinanceConfig | None = None) -> None:
        self._config = config or BinanceConfig.from_env()

    def submit_order(self, request: OrderRequest) -> OrderResult:
        payload = submit_order_api(
            self._config,
            map_order_request_to_binance_params(request),
        )
        return map_binance_order_to_result(payload)

    def submit_take_profit_stop_loss_orders(
        self,
        symbol: Symbol,
        position_direction: SignalDirection,
        take_profit: Decimal,
        stop_loss: Decimal,
        client_order_id_prefix: str,
    ) -> tuple[OrderResult, OrderResult]:
        close_side = _opposite_side(position_direction)
        take_profit_result = self.submit_order(
            OrderRequest.take_profit_market(
                client_order_id=f"{client_order_id_prefix}-tp",
                symbol=symbol,
                side=close_side,
                stop_price=take_profit,
            )
        )
        stop_loss_result = self.submit_order(
            OrderRequest.stop_market(
                client_order_id=f"{client_order_id_prefix}-sl",
                symbol=symbol,
                side=close_side,
                stop_price=stop_loss,
            )
        )
        return take_profit_result, stop_loss_result

    def load_execution_reports(
        self,
        symbol: Symbol,
        since: datetime,
        until: datetime,
    ) -> tuple[ExecutionReport, ...]:
        payloads = load_orders_api(
            self._config,
            symbol=symbol.pair,
            start_time=_to_epoch_millis(since),
            end_time=_to_epoch_millis(until),
        )
        return tuple(
            map_binance_order_to_execution_report(payload, symbol) for payload in payloads
        )


def _to_epoch_millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _opposite_side(direction: SignalDirection) -> SignalDirection:
    if direction is SignalDirection.LONG:
        return SignalDirection.SHORT
    return SignalDirection.LONG


def submit_order_api(
    config: BinanceConfig,
    params: Mapping[str, object],
) -> Mapping[str, object]:
    return cast(
        Mapping[str, object],
        request_json(
            config,
            "POST",
            "/fapi/v1/order",
            params=params,
            signed=True,
        ),
    )


def load_orders_api(
    config: BinanceConfig,
    symbol: str,
    start_time: int,
    end_time: int,
) -> list[Mapping[str, object]]:
    return cast(
        list[Mapping[str, object]],
        request_json(
            config,
            "GET",
            "/fapi/v1/allOrders",
            params={
                "symbol": symbol,
                "startTime": start_time,
                "endTime": end_time,
            },
            signed=True,
        ),
    )
