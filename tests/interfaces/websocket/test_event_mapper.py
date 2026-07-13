from datetime import datetime, timezone
from decimal import Decimal

from src.domain.market import Symbol
from src.domain.position import Position, PositionEvent, PositionStatus
from src.domain.signal import SignalDirection
from src.interfaces.websocket import PositionEventMapper


def test_mapper_applies_position_event_and_keeps_update_context() -> None:
    position = Position.open(
        symbol=Symbol("BTC", "USDT"),
        direction=SignalDirection.LONG,
        quantity=Decimal("1.0"),
        average_entry_price=Decimal("60000"),
    )
    event = PositionEvent.decrease(quantity=Decimal("0.4"), price=Decimal("61000"))
    received_at = datetime(2026, 6, 11, 1, 2, 3, tzinfo=timezone.utc)

    update = PositionEventMapper().apply(
        stream_name="binance-user-data",
        position=position,
        event=event,
        received_at=received_at,
    )

    assert update.stream_name == "binance-user-data"
    assert update.received_at == received_at
    assert update.previous_position is position
    assert update.event is event
    assert update.position.quantity == Decimal("0.6")
    assert update.position.status is PositionStatus.OPEN
