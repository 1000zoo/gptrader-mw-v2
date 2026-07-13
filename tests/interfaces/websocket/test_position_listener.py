import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from src.domain.market import Symbol
from src.domain.position import Position, PositionEvent, PositionEventType, PositionStatus
from src.domain.signal import SignalDirection
from src.interfaces.websocket import PositionListener


class FakePositionEventStream:
    def __init__(
        self,
        events: tuple[PositionEvent, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.events = events
        self.error = error
        self.handlers = []
        self.max_reconnects: int | None = None

    async def consume(self, handler, *, max_reconnects=None) -> None:
        self.handlers.append(handler)
        self.max_reconnects = max_reconnects
        for event in self.events:
            await handler(event)
        if self.error is not None:
            raise self.error


def _open_position() -> Position:
    return Position.open(
        symbol=Symbol("BTC", "USDT"),
        direction=SignalDirection.LONG,
        quantity=Decimal("1.0"),
        average_entry_price=Decimal("60000"),
    )


def test_listener_consumes_stream_events_and_returns_final_position() -> None:
    stream = FakePositionEventStream(
        events=(
            PositionEvent.increase(
                direction=SignalDirection.LONG,
                quantity=Decimal("0.5"),
                price=Decimal("62000"),
            ),
            PositionEvent.decrease(quantity=Decimal("0.25"), price=Decimal("63000")),
        )
    )
    received_updates = []
    listener = PositionListener(
        stream,
        now=lambda: datetime(2026, 6, 11, 1, 2, 3, tzinfo=timezone.utc),
    )

    run = asyncio.run(
        listener.listen(
            stream_name="binance-user-data",
            initial_position=_open_position(),
            update_handler=received_updates.append,
            max_reconnects=2,
        )
    )

    assert stream.max_reconnects == 2
    assert run.succeeded is True
    assert run.error is None
    assert run.position.quantity == Decimal("1.25")
    assert len(run.updates) == 2
    assert received_updates == list(run.updates)
    assert run.updates[0].event.event_type is PositionEventType.INCREASE
    assert run.updates[1].previous_position.quantity == Decimal("1.5")


def test_listener_captures_stream_error_and_keeps_applied_updates() -> None:
    error = ConnectionError("stream stopped")
    stream = FakePositionEventStream(
        events=(PositionEvent.decrease(quantity=Decimal("1.0")),),
        error=error,
    )
    listener = PositionListener(stream)

    run = asyncio.run(
        listener.listen(
            stream_name="binance-user-data",
            initial_position=_open_position(),
        )
    )

    assert run.succeeded is False
    assert run.error is error
    assert len(run.updates) == 1
    assert run.position.status is PositionStatus.CLOSED
