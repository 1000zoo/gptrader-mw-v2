from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.domain.market.symbol import Symbol
from src.domain.market.timeframe import Timeframe


@dataclass(frozen=True)
class Candle:
    symbol: Symbol
    timeframe: Timeframe
    opened_at: datetime
    closed_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if self.closed_at <= self.opened_at:
            raise ValueError("closed_at must be after opened_at")

        interval_seconds = (self.closed_at - self.opened_at).total_seconds()
        if interval_seconds != self.timeframe.duration_seconds:
            raise ValueError("candle interval must match timeframe")

        if self.low_price > self.high_price:
            raise ValueError("low_price must be less than or equal to high_price")

        for field_name in ("open_price", "close_price"):
            price = getattr(self, field_name)
            if price < self.low_price or price > self.high_price:
                raise ValueError(f"{field_name} must be within low_price and high_price")

        if self.volume < Decimal("0"):
            raise ValueError("volume must be greater than or equal to zero")
