from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe


def make_candle(opened_at: datetime, symbol: Symbol | None = None) -> Candle:
    timeframe = Timeframe(1, "m")
    return Candle(
        symbol=symbol or Symbol("BTC", "USDT"),
        timeframe=timeframe,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(seconds=timeframe.duration_seconds),
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("105"),
        volume=Decimal("1"),
    )


def test_market_snapshot_exposes_candles_for_one_symbol_and_timeframe():
    first = make_candle(datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc))
    second = make_candle(datetime(2026, 5, 12, 0, 1, tzinfo=timezone.utc))

    snapshot = MarketSnapshot(candles=(first, second))

    assert snapshot.symbol == Symbol("BTC", "USDT")
    assert snapshot.timeframe == Timeframe(1, "m")
    assert snapshot.opened_at == first.opened_at
    assert snapshot.closed_at == second.closed_at
    assert snapshot.latest_candle == second


def test_market_snapshot_rejects_empty_candles():
    with pytest.raises(ValueError, match="candles"):
        MarketSnapshot(candles=())


def test_market_snapshot_rejects_mixed_symbols():
    first = make_candle(datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc))
    second = make_candle(
        datetime(2026, 5, 12, 0, 1, tzinfo=timezone.utc),
        symbol=Symbol("ETH", "USDT"),
    )

    with pytest.raises(ValueError, match="symbol"):
        MarketSnapshot(candles=(first, second))


def test_market_snapshot_rejects_non_chronological_candles():
    first = make_candle(datetime(2026, 5, 12, 0, 1, tzinfo=timezone.utc))
    second = make_candle(datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc))

    with pytest.raises(ValueError, match="chronological"):
        MarketSnapshot(candles=(first, second))
