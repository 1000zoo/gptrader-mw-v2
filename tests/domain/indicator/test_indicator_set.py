from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.domain.indicator import IndicatorSet, IndicatorValue
from src.domain.market import Symbol, Timeframe


def make_value(
    name: str,
    measured_at: datetime,
    value: Decimal = Decimal("1"),
) -> IndicatorValue:
    return IndicatorValue(name=name, value=value, measured_at=measured_at)


def test_indicator_set_exposes_values_for_one_symbol_timeframe_and_candle_time():
    measured_at = datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc)
    rsi = make_value("rsi", measured_at, Decimal("52.1"))
    atr = make_value("atr", measured_at, Decimal("14.2"))

    indicators = IndicatorSet(
        symbol=Symbol("BTC", "USDT"),
        timeframe=Timeframe(1, "m"),
        measured_at=measured_at,
        values=(rsi, atr),
    )

    assert indicators.get("rsi") == rsi
    assert indicators.require("atr").value == Decimal("14.2")
    assert indicators.keys == ("atr", "rsi")


def test_indicator_set_rejects_values_from_different_candle_time():
    measured_at = datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc)
    later = datetime(2026, 5, 24, 0, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="measured_at"):
        IndicatorSet(
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "m"),
            measured_at=measured_at,
            values=(make_value("rsi", later),),
        )


def test_indicator_set_rejects_duplicate_keys():
    measured_at = datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="duplicate"):
        IndicatorSet(
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "m"),
            measured_at=measured_at,
            values=(
                make_value("rsi", measured_at),
                make_value("RSI", measured_at),
            ),
        )


def test_indicator_set_requires_existing_value_when_requested():
    measured_at = datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc)
    indicators = IndicatorSet(
        symbol=Symbol("BTC", "USDT"),
        timeframe=Timeframe(1, "m"),
        measured_at=measured_at,
        values=(make_value("rsi", measured_at),),
    )

    with pytest.raises(KeyError, match="missing indicator"):
        indicators.require("atr")
