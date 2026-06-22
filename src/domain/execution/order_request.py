from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from src.domain.market import Symbol
from src.domain.signal import SignalDirection


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    TAKE_PROFIT_MARKET = "take_profit_market"
    STOP_MARKET = "stop_market"


@dataclass(frozen=True)
class OrderRequest:
    client_order_id: str
    symbol: Symbol
    side: SignalDirection
    order_type: OrderType
    quantity: Decimal | None = None
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    reduce_only: bool = False
    close_position: bool = False

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("client_order_id is required")
        if self.side is SignalDirection.WAIT:
            raise ValueError("side must be LONG or SHORT")
        if self.close_position:
            if self.quantity is not None:
                raise ValueError("close_position order quantity must be empty")
        elif self.quantity is None or self.quantity <= Decimal("0"):
            raise ValueError("quantity must be positive")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market order limit_price must be empty")
        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None:
                raise ValueError("limit_price is required")
            if self.limit_price <= Decimal("0"):
                raise ValueError("limit_price must be positive")
        elif self.limit_price is not None:
            raise ValueError("limit_price is only valid for limit orders")
        if self.order_type in {OrderType.TAKE_PROFIT_MARKET, OrderType.STOP_MARKET}:
            if self.stop_price is None:
                raise ValueError("stop_price is required")
            if self.stop_price <= Decimal("0"):
                raise ValueError("stop_price must be positive")
            if not self.close_position:
                raise ValueError("protective market orders must close_position")
        elif self.stop_price is not None:
            raise ValueError("stop_price is only valid for protective market orders")

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

    @classmethod
    def take_profit_market(
        cls,
        client_order_id: str,
        symbol: Symbol,
        side: SignalDirection,
        stop_price: Decimal,
    ) -> "OrderRequest":
        return cls(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.TAKE_PROFIT_MARKET,
            stop_price=stop_price,
            close_position=True,
        )

    @classmethod
    def stop_market(
        cls,
        client_order_id: str,
        symbol: Symbol,
        side: SignalDirection,
        stop_price: Decimal,
    ) -> "OrderRequest":
        return cls(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.STOP_MARKET,
            stop_price=stop_price,
            close_position=True,
        )
