from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.domain.market import Candle, Symbol, Timeframe


def test_candle_accepts_vendor_neutral_ohlcv_fields():
    candle = Candle(
        symbol=Symbol("btc", "usdt"),
        timeframe=Timeframe(1, "m"),
        opened_at=datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc),
        closed_at=datetime(2026, 5, 12, 0, 1, tzinfo=timezone.utc),
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("105"),
        volume=Decimal("12.5"),
    )

    assert candle.symbol.pair == "BTCUSDT"
    assert candle.timeframe.label == "1m"
    assert candle.open_price == Decimal("100")
    assert candle.high_price == Decimal("110")
    assert candle.low_price == Decimal("90")
    assert candle.close_price == Decimal("105")
    assert candle.volume == Decimal("12.5")


def test_candle_rejects_prices_outside_high_low_range():
    with pytest.raises(ValueError, match="high_price"):
        Candle(
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "m"),
            opened_at=datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc),
            closed_at=datetime(2026, 5, 12, 0, 1, tzinfo=timezone.utc),
            open_price=Decimal("100"),
            high_price=Decimal("99"),
            low_price=Decimal("90"),
            close_price=Decimal("95"),
            volume=Decimal("1"),
        )


def test_candle_rejects_negative_volume():
    with pytest.raises(ValueError, match="volume"):
        Candle(
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "m"),
            opened_at=datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc),
            closed_at=datetime(2026, 5, 12, 0, 1, tzinfo=timezone.utc),
            open_price=Decimal("100"),
            high_price=Decimal("110"),
            low_price=Decimal("90"),
            close_price=Decimal("105"),
            volume=Decimal("-1"),
        )


def test_candle_requires_interval_to_match_timeframe():
    with pytest.raises(ValueError, match="timeframe"):
        Candle(
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "m"),
            opened_at=datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc),
            closed_at=datetime(2026, 5, 12, 0, 2, tzinfo=timezone.utc),
            open_price=Decimal("100"),
            high_price=Decimal("110"),
            low_price=Decimal("90"),
            close_price=Decimal("105"),
            volume=Decimal("1"),
        )
