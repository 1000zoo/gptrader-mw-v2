from dataclasses import dataclass
from decimal import Decimal

from src.domain.market import Symbol
from src.domain.position.position_event import PositionEvent, PositionEventType
from src.domain.position.position_status import PositionStatus
from src.domain.signal import SignalDirection


@dataclass(frozen=True)
class Position:
    symbol: Symbol
    direction: SignalDirection
    quantity: Decimal
    average_entry_price: Decimal
    status: PositionStatus

    def __post_init__(self) -> None:
        if self.direction is SignalDirection.WAIT:
            raise ValueError("position direction must be LONG or SHORT")
        if self.quantity < Decimal("0"):
            raise ValueError("quantity cannot be negative")
        if self.average_entry_price <= Decimal("0"):
            raise ValueError("average_entry_price must be positive")
        if self.status is PositionStatus.OPEN and self.quantity <= Decimal("0"):
            raise ValueError("open position quantity must be positive")
        if self.status is PositionStatus.CLOSED and self.quantity != Decimal("0"):
            raise ValueError("closed position quantity must be zero")

    @classmethod
    def open(
        cls,
        symbol: Symbol,
        direction: SignalDirection,
        quantity: Decimal,
        average_entry_price: Decimal,
    ) -> "Position":
        return cls(
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            average_entry_price=average_entry_price,
            status=PositionStatus.OPEN,
        )

    @classmethod
    def closed(
        cls,
        symbol: Symbol,
        direction: SignalDirection,
        average_entry_price: Decimal,
    ) -> "Position":
        return cls(
            symbol=symbol,
            direction=direction,
            quantity=Decimal("0"),
            average_entry_price=average_entry_price,
            status=PositionStatus.CLOSED,
        )

    def apply_event(self, event: PositionEvent) -> "Position":
        if self.status is PositionStatus.CLOSED:
            raise ValueError("cannot apply event to closed position")

        if event.event_type is PositionEventType.INCREASE:
            return self._increase(event)

        if event.event_type in {PositionEventType.DECREASE, PositionEventType.CLOSE}:
            return self._decrease(event)

        raise ValueError(f"unsupported position event type: {event.event_type}")

    def _increase(self, event: PositionEvent) -> "Position":
        if event.direction is not self.direction:
            raise ValueError("increase event direction must match position direction")
        if event.price is None:
            raise ValueError("increase event price is required")

        new_quantity = self.quantity + event.quantity
        weighted_entry_value = (
            self.average_entry_price * self.quantity
        ) + (event.price * event.quantity)
        new_average_entry_price = weighted_entry_value / new_quantity

        return Position.open(
            symbol=self.symbol,
            direction=self.direction,
            quantity=new_quantity,
            average_entry_price=new_average_entry_price,
        )

    def _decrease(self, event: PositionEvent) -> "Position":
        if event.quantity > self.quantity:
            raise ValueError("event quantity cannot exceed remaining position quantity")

        remaining_quantity = self.quantity - event.quantity
        if remaining_quantity == Decimal("0"):
            return Position.closed(
                symbol=self.symbol,
                direction=self.direction,
                average_entry_price=self.average_entry_price,
            )

        return Position.open(
            symbol=self.symbol,
            direction=self.direction,
            quantity=remaining_quantity,
            average_entry_price=self.average_entry_price,
        )
