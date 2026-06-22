from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.ports import MarketDataPort


def make_candle() -> Candle:
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    opened_at = datetime(2026, 1, 1, 0, 0)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=1),
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("105"),
        volume=Decimal("12"),
    )


class InMemoryMarketDataPort:
    def __init__(self, candles: tuple[Candle, ...]) -> None:
        self.candles = candles

    def load_candles(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        return tuple(
            candle
            for candle in self.candles
            if candle.symbol == symbol and candle.timeframe == timeframe
        )[:limit]

    def load_snapshot(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        limit: int,
    ) -> MarketSnapshot:
        return MarketSnapshot(self.load_candles(symbol, timeframe, limit))

    def load_candles_between(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[Candle, ...]:
        return tuple(
            candle
            for candle in self.candles
            if candle.symbol == symbol
            and candle.timeframe == timeframe
            and start_at <= candle.opened_at < end_at
        )


def test_market_data_port_is_protocol_contract():
    assert issubclass(MarketDataPort, Protocol)


def test_market_data_port_loads_candles_and_snapshot():
    candle = make_candle()
    port = InMemoryMarketDataPort((candle,))

    candles = port.load_candles(candle.symbol, candle.timeframe, limit=1)
    ranged = port.load_candles_between(
        candle.symbol,
        candle.timeframe,
        candle.opened_at,
        candle.closed_at,
    )
    snapshot = port.load_snapshot(candle.symbol, candle.timeframe, limit=1)

    assert isinstance(port, MarketDataPort)
    assert candles == (candle,)
    assert ranged == (candle,)
    assert snapshot.latest_candle == candle
