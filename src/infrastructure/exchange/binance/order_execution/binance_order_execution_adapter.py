from datetime import datetime
from typing import Any

from src.domain.execution import ExecutionReport, OrderRequest, OrderResult
from src.domain.market import Symbol
from src.domain.ports import OrderExecutionPort
from src.infrastructure.exchange.binance.order_execution.binance_order_execution_mapper import (
    map_binance_order_to_result,
    map_order_request_to_binance_params,
)


class BinanceOrderExecutionAdapter(OrderExecutionPort):
    def __init__(self, client: Any) -> None:
        self._client = client

    def submit_order(self, request: OrderRequest) -> OrderResult:
        payload = self._client.create_order(**map_order_request_to_binance_params(request))
        return map_binance_order_to_result(payload)

    def load_execution_reports(
        self,
        symbol: Symbol,
        since: datetime,
        until: datetime,
    ) -> tuple[ExecutionReport, ...]:
        raise NotImplementedError(
            "Binance execution report history is deferred to a later Module N pass"
        )
