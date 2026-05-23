from decimal import Decimal

import pytest

from src.domain.execution import ExecutionReport, OrderRequest, OrderResult
from src.domain.market import Symbol
from src.domain.position import PositionEventType
from src.domain.signal import SignalDirection


def test_execution_report_combines_order_request_and_result():
    request = OrderRequest.market(
        client_order_id="entry-1",
        symbol=Symbol("btc", "usdt"),
        side=SignalDirection.LONG,
        quantity=Decimal("0.25"),
    )
    result = OrderResult.accepted(client_order_id="entry-1")

    report = ExecutionReport(request=request, result=result)

    assert report.request == request
    assert report.result == result


def test_filled_execution_report_converts_to_position_increase_event():
    report = ExecutionReport(
        request=OrderRequest.market(
            client_order_id="entry-1",
            symbol=Symbol("btc", "usdt"),
            side=SignalDirection.LONG,
            quantity=Decimal("0.25"),
        ),
        result=OrderResult.filled(
            client_order_id="entry-1",
            executed_quantity=Decimal("0.25"),
            average_price=Decimal("70000"),
        ),
    )

    event = report.to_position_event()

    assert event.event_type is PositionEventType.INCREASE
    assert event.direction is SignalDirection.LONG
    assert event.quantity == Decimal("0.25")
    assert event.price == Decimal("70000")


def test_non_filled_execution_report_cannot_convert_to_position_event():
    report = ExecutionReport(
        request=OrderRequest.market(
            client_order_id="entry-1",
            symbol=Symbol("btc", "usdt"),
            side=SignalDirection.LONG,
            quantity=Decimal("0.25"),
        ),
        result=OrderResult.accepted(client_order_id="entry-1"),
    )

    with pytest.raises(ValueError, match="filled"):
        report.to_position_event()


def test_reduce_only_execution_report_cannot_convert_to_position_increase_event():
    report = ExecutionReport(
        request=OrderRequest.market(
            client_order_id="exit-1",
            symbol=Symbol("btc", "usdt"),
            side=SignalDirection.LONG,
            quantity=Decimal("0.25"),
            reduce_only=True,
        ),
        result=OrderResult.filled(
            client_order_id="exit-1",
            executed_quantity=Decimal("0.25"),
            average_price=Decimal("70000"),
        ),
    )

    with pytest.raises(ValueError, match="reduce_only"):
        report.to_position_event()


def test_execution_report_rejects_mismatched_client_order_id():
    with pytest.raises(ValueError, match="client_order_id"):
        ExecutionReport(
            request=OrderRequest.market(
                client_order_id="entry-1",
                symbol=Symbol("btc", "usdt"),
                side=SignalDirection.LONG,
                quantity=Decimal("0.25"),
            ),
            result=OrderResult.accepted(client_order_id="entry-2"),
        )
