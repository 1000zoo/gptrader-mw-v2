from datetime import datetime, timezone
from decimal import Decimal

from src.application.usecases.trade import SyncPositionCommand, SyncPositionUseCase
from src.domain.execution import ExecutionReport, OrderRequest, OrderResult
from src.domain.market import Symbol
from src.domain.position import Position, PositionStatus
from src.domain.signal import SignalDirection


class FakeOrderExecution:
    def __init__(self, reports):
        self.reports = tuple(reports)
        self.requests = []

    def load_execution_reports(self, symbol, since, until):
        self.requests.append((symbol, since, until))
        return self.reports


def _position() -> Position:
    return Position.open(
        symbol=Symbol("btc", "usdt"),
        direction=SignalDirection.LONG,
        quantity=Decimal("0.5"),
        average_entry_price=Decimal("70000"),
    )


def _filled_reduce_only_report(position: Position, quantity: Decimal) -> ExecutionReport:
    request = OrderRequest.market(
        client_order_id="close-1",
        symbol=position.symbol,
        side=SignalDirection.SHORT,
        quantity=quantity,
        reduce_only=True,
    )
    return ExecutionReport(
        request=request,
        result=OrderResult.filled(
            client_order_id="close-1",
            executed_quantity=quantity,
            average_price=Decimal("71000"),
            exchange_order_id="exchange-close-1",
        ),
    )


def test_sync_position_usecase_applies_loaded_reduce_only_reports_to_position():
    position = _position()
    report = _filled_reduce_only_report(position, Decimal("0.25"))
    since = datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 5, 24, 1, 0, tzinfo=timezone.utc)
    order_execution = FakeOrderExecution((report,))
    usecase = SyncPositionUseCase(order_execution=order_execution)

    result = usecase.sync(
        SyncPositionCommand(position=position, since=since, until=until)
    )

    assert result.position.quantity == Decimal("0.25")
    assert result.position.status is PositionStatus.OPEN
    assert result.applied_reports == (report,)
    assert order_execution.requests == [(position.symbol, since, until)]


def test_sync_position_usecase_closes_position_when_reports_reduce_full_quantity():
    position = _position()
    report = _filled_reduce_only_report(position, Decimal("0.5"))
    usecase = SyncPositionUseCase(order_execution=FakeOrderExecution((report,)))

    result = usecase.sync(
        SyncPositionCommand(
            position=position,
            since=datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc),
            until=datetime(2026, 5, 24, 1, 0, tzinfo=timezone.utc),
        )
    )

    assert result.position.quantity == Decimal("0")
    assert result.position.status is PositionStatus.CLOSED
