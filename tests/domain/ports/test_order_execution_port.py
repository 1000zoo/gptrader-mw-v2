from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from src.domain.execution import ExecutionReport, OrderRequest, OrderResult
from src.domain.market import Symbol
from src.domain.ports import OrderExecutionPort
from src.domain.signal import SignalDirection


class InMemoryOrderExecutionPort:
    def __init__(self) -> None:
        self.reports: list[ExecutionReport] = []

    def submit_order(self, request: OrderRequest) -> OrderResult:
        result = OrderResult.accepted(
            client_order_id=request.client_order_id,
            exchange_order_id="exchange-1",
        )
        self.reports.append(ExecutionReport(request=request, result=result))
        return result

    def submit_take_profit_stop_loss_orders(
        self,
        symbol: Symbol,
        position_direction: SignalDirection,
        take_profit: Decimal,
        stop_loss: Decimal,
        client_order_id_prefix: str,
    ) -> tuple[OrderResult, OrderResult]:
        take_profit_result = OrderResult.accepted(
            client_order_id=f"{client_order_id_prefix}-tp",
            exchange_order_id="exchange-tp",
        )
        stop_loss_result = OrderResult.accepted(
            client_order_id=f"{client_order_id_prefix}-sl",
            exchange_order_id="exchange-sl",
        )
        return take_profit_result, stop_loss_result

    def load_execution_reports(
        self,
        symbol: Symbol,
        since: datetime,
        until: datetime,
    ) -> tuple[ExecutionReport, ...]:
        return tuple(self.reports)


def test_order_execution_port_is_protocol_contract():
    assert issubclass(OrderExecutionPort, Protocol)


def test_order_execution_port_submits_order_and_loads_reports():
    symbol = Symbol("BTC", "USDT")
    request = OrderRequest.market(
        client_order_id="order-1",
        symbol=symbol,
        side=SignalDirection.LONG,
        quantity=Decimal("0.1"),
    )
    port = InMemoryOrderExecutionPort()

    result = port.submit_order(request)
    reports = port.load_execution_reports(
        symbol=symbol,
        since=datetime(2026, 1, 1),
        until=datetime(2026, 1, 1) + timedelta(days=1),
    )

    assert isinstance(port, OrderExecutionPort)
    assert result.exchange_order_id == "exchange-1"
    assert reports[0].request == request
