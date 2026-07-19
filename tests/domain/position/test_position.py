from decimal import Decimal

import pytest

from src.domain.market import Symbol
from src.domain.position import Position, PositionEvent, PositionStatus
from src.domain.signal import SignalDirection


def test_position_opens_with_symbol_direction_quantity_and_average_entry_price():
    symbol = Symbol("btc", "usdt")

    position = Position.open(
        symbol=symbol,
        direction=SignalDirection.LONG,
        quantity=Decimal("0.5"),
        average_entry_price=Decimal("70000"),
    )

    assert position.symbol == symbol
    assert position.direction is SignalDirection.LONG
    assert position.quantity == Decimal("0.5")
    assert position.average_entry_price == Decimal("70000")
    assert position.status is PositionStatus.OPEN


def test_position_rejects_wait_direction():
    with pytest.raises(ValueError, match="direction"):
        Position.open(
            symbol=Symbol("btc", "usdt"),
            direction=SignalDirection.WAIT,
            quantity=Decimal("0.5"),
            average_entry_price=Decimal("70000"),
        )


def test_position_rejects_non_positive_quantity():
    with pytest.raises(ValueError, match="quantity"):
        Position.open(
            symbol=Symbol("btc", "usdt"),
            direction=SignalDirection.LONG,
            quantity=Decimal("0"),
            average_entry_price=Decimal("70000"),
        )


def test_position_closed_state_has_zero_quantity():
    position = Position.closed(
        symbol=Symbol("btc", "usdt"),
        direction=SignalDirection.SHORT,
        average_entry_price=Decimal("69000"),
    )

    assert position.quantity == Decimal("0")
    assert position.status is PositionStatus.CLOSED


def test_position_increase_recalculates_weighted_average_entry_price():
    position = Position.open(
        symbol=Symbol("btc", "usdt"),
        direction=SignalDirection.LONG,
        quantity=Decimal("1"),
        average_entry_price=Decimal("70000"),
    )

    updated = position.apply_event(
        PositionEvent.increase(
            direction=SignalDirection.LONG,
            quantity=Decimal("1"),
            price=Decimal("72000"),
        )
    )

    assert updated.quantity == Decimal("2")
    assert updated.average_entry_price == Decimal("71000")
    assert updated.status is PositionStatus.OPEN


def test_position_decrease_keeps_average_entry_price_and_reduces_quantity():
    position = Position.open(
        symbol=Symbol("btc", "usdt"),
        direction=SignalDirection.SHORT,
        quantity=Decimal("1.5"),
        average_entry_price=Decimal("69000"),
    )

    updated = position.apply_event(PositionEvent.decrease(quantity=Decimal("0.5")))

    assert updated.quantity == Decimal("1.0")
    assert updated.average_entry_price == Decimal("69000")
    assert updated.status is PositionStatus.OPEN


def test_position_decrease_full_quantity_closes_position():
    position = Position.open(
        symbol=Symbol("btc", "usdt"),
        direction=SignalDirection.LONG,
        quantity=Decimal("0.5"),
        average_entry_price=Decimal("70000"),
    )

    updated = position.apply_event(PositionEvent.decrease(quantity=Decimal("0.5")))

    assert updated.quantity == Decimal("0")
    assert updated.status is PositionStatus.CLOSED


def test_position_close_event_closes_position():
    position = Position.open(
        symbol=Symbol("btc", "usdt"),
        direction=SignalDirection.LONG,
        quantity=Decimal("0.5"),
        average_entry_price=Decimal("70000"),
    )

    updated = position.apply_event(PositionEvent.close(quantity=Decimal("0.5")))

    assert updated.quantity == Decimal("0")
    assert updated.status is PositionStatus.CLOSED


def test_position_rejects_decrease_larger_than_remaining_quantity():
    position = Position.open(
        symbol=Symbol("btc", "usdt"),
        direction=SignalDirection.LONG,
        quantity=Decimal("0.5"),
        average_entry_price=Decimal("70000"),
    )

    with pytest.raises(ValueError, match="remaining"):
        position.apply_event(PositionEvent.decrease(quantity=Decimal("0.6")))


def test_position_rejects_increase_with_different_direction():
    position = Position.open(
        symbol=Symbol("btc", "usdt"),
        direction=SignalDirection.LONG,
        quantity=Decimal("0.5"),
        average_entry_price=Decimal("70000"),
    )

    with pytest.raises(ValueError, match="direction"):
        position.apply_event(
            PositionEvent.increase(
                direction=SignalDirection.SHORT,
                quantity=Decimal("0.5"),
                price=Decimal("71000"),
            )
        )


def test_position_rejects_event_after_close():
    position = Position.closed(
        symbol=Symbol("btc", "usdt"),
        direction=SignalDirection.LONG,
        average_entry_price=Decimal("70000"),
    )

    with pytest.raises(ValueError, match="closed"):
        position.apply_event(PositionEvent.decrease(quantity=Decimal("0.1")))
