from decimal import Decimal

from src.domain.position import PositionEvent, PositionEventType
from src.domain.signal import SignalDirection


def test_position_event_increase_records_direction_quantity_and_price():
    event = PositionEvent.increase(
        direction=SignalDirection.LONG,
        quantity=Decimal("0.2"),
        price=Decimal("71000"),
    )

    assert event.event_type is PositionEventType.INCREASE
    assert event.direction is SignalDirection.LONG
    assert event.quantity == Decimal("0.2")
    assert event.price == Decimal("71000")


def test_position_event_decrease_records_quantity_and_price():
    event = PositionEvent.decrease(
        quantity=Decimal("0.1"),
        price=Decimal("72000"),
    )

    assert event.event_type is PositionEventType.DECREASE
    assert event.direction is None
    assert event.quantity == Decimal("0.1")
    assert event.price == Decimal("72000")


def test_position_event_close_uses_close_type_and_remaining_quantity():
    event = PositionEvent.close(quantity=Decimal("0.5"))

    assert event.event_type is PositionEventType.CLOSE
    assert event.quantity == Decimal("0.5")
    assert event.price is None
