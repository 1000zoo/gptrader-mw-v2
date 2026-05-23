from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class OrderStatus(Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELED = "canceled"


@dataclass(frozen=True)
class OrderResult:
    client_order_id: str
    status: OrderStatus
    exchange_order_id: str | None = None
    executed_quantity: Decimal | None = None
    average_price: Decimal | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("client_order_id is required")

        if self.status is OrderStatus.REJECTED:
            if self.failure_reason is None or not self.failure_reason.strip():
                raise ValueError("failure_reason is required")
        elif self.failure_reason is not None:
            raise ValueError("failure_reason is only valid for rejected orders")

        if self.status in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}:
            if self.executed_quantity is None:
                raise ValueError("executed_quantity is required")
            if self.executed_quantity <= Decimal("0"):
                raise ValueError("executed_quantity must be positive")
            if self.average_price is None:
                raise ValueError("average_price is required")
            if self.average_price <= Decimal("0"):
                raise ValueError("average_price must be positive")
        elif self.executed_quantity is not None or self.average_price is not None:
            raise ValueError("execution values are only valid for filled orders")

    @classmethod
    def accepted(
        cls,
        client_order_id: str,
        exchange_order_id: str | None = None,
    ) -> "OrderResult":
        return cls(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            status=OrderStatus.ACCEPTED,
        )

    @classmethod
    def rejected(cls, client_order_id: str, failure_reason: str) -> "OrderResult":
        return cls(
            client_order_id=client_order_id,
            status=OrderStatus.REJECTED,
            failure_reason=failure_reason,
        )

    @classmethod
    def filled(
        cls,
        client_order_id: str,
        executed_quantity: Decimal,
        average_price: Decimal,
        exchange_order_id: str | None = None,
    ) -> "OrderResult":
        return cls(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            status=OrderStatus.FILLED,
            executed_quantity=executed_quantity,
            average_price=average_price,
        )

    @classmethod
    def partially_filled(
        cls,
        client_order_id: str,
        executed_quantity: Decimal,
        average_price: Decimal,
        exchange_order_id: str | None = None,
    ) -> "OrderResult":
        return cls(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            status=OrderStatus.PARTIALLY_FILLED,
            executed_quantity=executed_quantity,
            average_price=average_price,
        )

    @classmethod
    def canceled(
        cls,
        client_order_id: str,
        exchange_order_id: str | None = None,
    ) -> "OrderResult":
        return cls(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            status=OrderStatus.CANCELED,
        )
