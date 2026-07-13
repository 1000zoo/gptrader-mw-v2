from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from src.domain.signal import SignalDirection


class PositionEventType(Enum):
    INCREASE = "increase"
    DECREASE = "decrease"
    CLOSE = "close"


@dataclass(frozen=True)
class PositionEvent:
    event_type: PositionEventType
    quantity: Decimal
    price: Decimal | None = None
    direction: SignalDirection | None = None

    def __post_init__(self) -> None:
        if self.quantity <= Decimal("0"):
            raise ValueError("quantity must be positive")
        if self.price is not None and self.price <= Decimal("0"):
            raise ValueError("price must be positive")
        if self.direction is SignalDirection.WAIT:
            raise ValueError("direction must be LONG or SHORT")

    @classmethod
    def increase(
        cls,
        direction: SignalDirection,
        quantity: Decimal,
        price: Decimal,
    ) -> "PositionEvent":
        return cls(
            event_type=PositionEventType.INCREASE,
            direction=direction,
            quantity=quantity,
            price=price,
        )

    @classmethod
    def decrease(cls, quantity: Decimal, price: Decimal | None = None) -> "PositionEvent":
        return cls(
            event_type=PositionEventType.DECREASE,
            quantity=quantity,
            price=price,
        )

    @classmethod
    def close(cls, quantity: Decimal, price: Decimal | None = None) -> "PositionEvent":
        return cls(
            event_type=PositionEventType.CLOSE,
            quantity=quantity,
            price=price,
        )
