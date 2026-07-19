from decimal import Decimal

from src.application.usecases.trade import (
    ClosePositionCommand,
    ClosePositionUseCase,
    TradeExecutionStatus,
)
from src.domain.execution import OrderResult
from src.domain.market import Symbol
from src.domain.position import Position
from src.domain.signal import SignalDirection


class FakeOrderExecution:
    def __init__(self):
        self.requests = []

    def submit_order(self, request):
        self.requests.append(request)
        return OrderResult.accepted(request.client_order_id, "exchange-close-1")


def test_close_position_usecase_submits_reduce_only_opposite_side_order():
    position = Position.open(
        symbol=Symbol("btc", "usdt"),
        direction=SignalDirection.LONG,
        quantity=Decimal("0.5"),
        average_entry_price=Decimal("70000"),
    )
    order_execution = FakeOrderExecution()
    usecase = ClosePositionUseCase(order_execution=order_execution)

    result = usecase.close(
        ClosePositionCommand(
            position=position,
            client_order_id_prefix="close-btc",
        )
    )

    assert result.status is TradeExecutionStatus.ORDER_SUBMITTED
    assert result.order_result == OrderResult.accepted(
        "close-btc-BTCUSDT",
        "exchange-close-1",
    )
    assert len(order_execution.requests) == 1
    request = order_execution.requests[0]
    assert request.client_order_id == "close-btc-BTCUSDT"
    assert request.symbol == position.symbol
    assert request.side is SignalDirection.SHORT
    assert request.quantity == Decimal("0.5")
    assert request.reduce_only is True


def test_close_position_usecase_skips_closed_positions():
    position = Position.closed(
        symbol=Symbol("btc", "usdt"),
        direction=SignalDirection.SHORT,
        average_entry_price=Decimal("70000"),
    )
    order_execution = FakeOrderExecution()
    usecase = ClosePositionUseCase(order_execution=order_execution)

    result = usecase.close(
        ClosePositionCommand(
            position=position,
            client_order_id_prefix="close-btc",
        )
    )

    assert result.status is TradeExecutionStatus.SKIPPED
    assert result.reason == "position_not_open"
    assert result.order_result is None
    assert order_execution.requests == []
