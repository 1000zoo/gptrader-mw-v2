from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from src.domain.execution import ExecutionReport, OrderRequest, OrderResult
from src.domain.market import Symbol
from src.domain.signal import SignalDirection


@runtime_checkable
class OrderExecutionPort(Protocol):
    def submit_order(self, request: OrderRequest) -> OrderResult:
        ...

    def submit_take_profit_stop_loss_orders(
        self,
        symbol: Symbol,
        position_direction: SignalDirection,
        take_profit: Decimal,
        stop_loss: Decimal,
        client_order_id_prefix: str,
    ) -> tuple[OrderResult, OrderResult]:
        ...

    def load_execution_reports(
        self,
        symbol: Symbol,
        since: datetime,
        until: datetime,
    ) -> tuple[ExecutionReport, ...]:
        ...
