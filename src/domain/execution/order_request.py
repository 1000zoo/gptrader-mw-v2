from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from src.domain.market import Symbol
from src.domain.signal import SignalDirection


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass(frozen=True)
class OrderRequest:
    client_order_id: str
    symbol: Symbol
    side: SignalDirection
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    reduce_only: bool = False

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("client_order_id is required")
        if self.side is SignalDirection.WAIT:
            raise ValueError("side must be LONG or SHORT")
        if self.quantity <= Decimal("0"):
            raise ValueError("quantity must be positive")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market order limit_price must be empty")
        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None:
                raise ValueError("limit_price is required")
            if self.limit_price <= Decimal("0"):
                raise ValueError("limit_price must be positive")

    @classmethod
    def market(
        cls,
        client_order_id: str,
        symbol: Symbol,
        side: SignalDirection,
        quantity: Decimal,
        reduce_only: bool = False,
    ) -> "OrderRequest":
        return cls(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            reduce_only=reduce_only,
        )

    @classmethod
    def limit(
        cls,
        client_order_id: str,
        symbol: Symbol,
        side: SignalDirection,
        quantity: Decimal,
        limit_price: Decimal,
        reduce_only: bool = False,
    ) -> "OrderRequest":
        return cls(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            limit_price=limit_price,
            reduce_only=reduce_only,
        )
