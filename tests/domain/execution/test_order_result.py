from decimal import Decimal

import pytest

from src.domain.execution import OrderResult, OrderStatus


def test_accepted_order_result_stores_order_identifiers():
    result = OrderResult.accepted(
        client_order_id="entry-1",
        exchange_order_id="binance-1",
    )

    assert result.client_order_id == "entry-1"
    assert result.exchange_order_id == "binance-1"
    assert result.status is OrderStatus.ACCEPTED
    assert result.failure_reason is None
    assert result.executed_quantity is None
    assert result.average_price is None


def test_rejected_order_result_stores_failure_reason():
    result = OrderResult.rejected(
        client_order_id="entry-1",
        failure_reason="insufficient margin",
    )

    assert result.status is OrderStatus.REJECTED
    assert result.failure_reason == "insufficient margin"


def test_filled_order_result_stores_execution_quantity_and_average_price():
    result = OrderResult.filled(
        client_order_id="entry-1",
        exchange_order_id="binance-1",
        executed_quantity=Decimal("0.25"),
        average_price=Decimal("70000"),
    )

    assert result.status is OrderStatus.FILLED
    assert result.executed_quantity == Decimal("0.25")
    assert result.average_price == Decimal("70000")


def test_successful_fill_rejects_non_positive_execution_values():
    with pytest.raises(ValueError, match="executed_quantity"):
        OrderResult.filled(
            client_order_id="entry-1",
            executed_quantity=Decimal("0"),
            average_price=Decimal("70000"),
        )

    with pytest.raises(ValueError, match="average_price"):
        OrderResult.filled(
            client_order_id="entry-1",
            executed_quantity=Decimal("0.25"),
            average_price=Decimal("0"),
        )
