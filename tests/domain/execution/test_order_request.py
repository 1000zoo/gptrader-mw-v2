from decimal import Decimal

import pytest

from src.domain.execution import OrderRequest, OrderType
from src.domain.market import Symbol
from src.domain.signal import SignalDirection


def test_market_order_request_stores_symbol_side_quantity_and_reduce_only_flag():
    symbol = Symbol("btc", "usdt")

    request = OrderRequest.market(
        client_order_id="entry-1",
        symbol=symbol,
        side=SignalDirection.LONG,
        quantity=Decimal("0.25"),
        reduce_only=False,
    )

    assert request.client_order_id == "entry-1"
    assert request.symbol == symbol
    assert request.side is SignalDirection.LONG
    assert request.order_type is OrderType.MARKET
    assert request.quantity == Decimal("0.25")
    assert request.limit_price is None
    assert request.reduce_only is False


def test_limit_order_request_requires_positive_limit_price():
    with pytest.raises(ValueError, match="limit_price"):
        OrderRequest.limit(
            client_order_id="entry-1",
            symbol=Symbol("btc", "usdt"),
            side=SignalDirection.SHORT,
            quantity=Decimal("0.25"),
            limit_price=Decimal("0"),
        )


def test_order_request_rejects_wait_side():
    with pytest.raises(ValueError, match="side"):
        OrderRequest.market(
            client_order_id="entry-1",
            symbol=Symbol("btc", "usdt"),
            side=SignalDirection.WAIT,
            quantity=Decimal("0.25"),
        )


def test_order_request_rejects_non_positive_quantity():
    with pytest.raises(ValueError, match="quantity"):
        OrderRequest.market(
            client_order_id="entry-1",
            symbol=Symbol("btc", "usdt"),
            side=SignalDirection.LONG,
            quantity=Decimal("0"),
        )
