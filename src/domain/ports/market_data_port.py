from datetime import datetime
from typing import Protocol, runtime_checkable

from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe


@runtime_checkable
class MarketDataPort(Protocol):
    def load_candles(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        ...

    def load_candles_between(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[Candle, ...]:
        ...

    def load_snapshot(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        limit: int,
    ) -> MarketSnapshot:
        ...
