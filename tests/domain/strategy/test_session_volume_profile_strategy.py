from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.domain.indicator import IndicatorSet
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.signal import SignalDirection
from src.domain.strategy import Strategy, StrategyContext
from src.domain.strategy.implementations import SessionVolumeProfileStrategy
from src.domain.strategy.implementations.session_volume_profile import _build_profile


SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")
START = datetime(2026, 6, 12, 0, 0, tzinfo=timezone.utc)


def make_candle(
    index: int,
    *,
    low: str,
    high: str,
    close: str,
    volume: str,
    open_price: str | None = None,
) -> Candle:
    opened_at = START + timedelta(minutes=index)
    return Candle(
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=1),
        open_price=Decimal(open_price or close),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
        volume=Decimal(volume),
    )


def make_context(candles: tuple[Candle, ...]) -> StrategyContext:
    market = MarketSnapshot(candles=candles)
    indicators = IndicatorSet(
        symbol=market.symbol,
        timeframe=market.timeframe,
        measured_at=market.latest_candle.closed_at,
        values=(),
    )
    return StrategyContext(market=market, indicators=indicators)


def test_build_profile_calculates_poc_value_area_and_total_volume() -> None:
    profile = _build_profile(
        (
            make_candle(0, low="100", high="100", close="100", volume="10"),
            make_candle(1, low="101", high="101", close="101", volume="30"),
            make_candle(2, low="102", high="102", close="102", volume="20"),
        ),
        price_bin_size=Decimal("1"),
        value_area_ratio=Decimal("0.70"),
    )

    assert profile.poc == Decimal("101")
    assert profile.value_area_low == Decimal("101")
    assert profile.value_area_high == Decimal("102")
    assert profile.total_volume == Decimal("60")
    assert profile.volume_by_price == {
        Decimal("100"): Decimal("10"),
        Decimal("101"): Decimal("30"),
        Decimal("102"): Decimal("20"),
    }


def test_build_profile_distributes_candle_volume_across_touched_bins() -> None:
    profile = _build_profile(
        (make_candle(0, low="100", high="102", close="101", volume="9"),),
        price_bin_size=Decimal("1"),
        value_area_ratio=Decimal("1"),
    )

    assert profile.volume_by_price == {
        Decimal("100"): Decimal("3"),
        Decimal("101"): Decimal("3"),
        Decimal("102"): Decimal("3"),
    }
    assert profile.poc == Decimal("100")


def test_strategy_waits_when_profile_has_insufficient_candles() -> None:
    context = make_context(
        (
            make_candle(0, low="100", high="100", close="100", volume="10"),
            make_candle(1, low="101", high="101", close="101", volume="12"),
        )
    )

    result = SessionVolumeProfileStrategy(
        price_bin_size=Decimal("1"),
        profile_min_candles=3,
    ).evaluate(context)

    assert result.name == "session-volume-profile"
    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["decision_type"] == "wait"
    assert result.signal.metadata["reason"] == "insufficient_candles"


def test_strategy_emits_long_for_lower_value_rejection() -> None:
    candles = (
        make_candle(0, low="100", high="100", close="100", volume="20"),
        make_candle(1, low="101", high="101", close="101", volume="30"),
        make_candle(2, low="102", high="102", close="102", volume="20"),
        make_candle(3, low="99", high="101", open_price="100", close="101", volume="12"),
    )

    result = SessionVolumeProfileStrategy(
        price_bin_size=Decimal("1"),
        rejection_wick_ratio=Decimal("0.40"),
    ).evaluate(make_context(candles))

    assert result.signal.direction is SignalDirection.LONG
    assert result.signal.reasons[0].code == "lower_value_rejection"
    assert result.metadata["decision_type"] == "lower_rejection"
    assert result.metadata["value_area_low"] == "100"
    assert Decimal(str(result.signal.reasons[0].metadata["lower_wick_ratio"])) >= Decimal("0.40")


def test_strategy_emits_short_for_upper_value_rejection() -> None:
    candles = (
        make_candle(0, low="100", high="100", close="100", volume="20"),
        make_candle(1, low="101", high="101", close="101", volume="30"),
        make_candle(2, low="102", high="102", close="102", volume="20"),
        make_candle(3, low="101", high="103", open_price="102", close="101", volume="12"),
    )

    result = SessionVolumeProfileStrategy(
        price_bin_size=Decimal("1"),
        rejection_wick_ratio=Decimal("0.40"),
    ).evaluate(make_context(candles))

    assert result.signal.direction is SignalDirection.SHORT
    assert result.signal.reasons[0].code == "upper_value_rejection"
    assert result.metadata["decision_type"] == "upper_rejection"
    assert result.metadata["value_area_high"] == "102"


def test_strategy_emits_long_for_confirmed_upper_value_breakout() -> None:
    candles = (
        make_candle(0, low="100", high="100", close="100", volume="10"),
        make_candle(1, low="101", high="101", close="101", volume="30"),
        make_candle(2, low="102", high="102", close="102", volume="10"),
        make_candle(3, low="103", high="103", close="103", volume="80"),
    )

    result = SessionVolumeProfileStrategy(
        price_bin_size=Decimal("1"),
        breakout_volume_multiplier=Decimal("1.20"),
    ).evaluate(make_context(candles))

    assert result.signal.direction is SignalDirection.LONG
    assert result.signal.reasons[0].code == "upper_value_breakout"
    assert result.metadata["decision_type"] == "upper_breakout"
    assert result.signal.confidence >= Decimal("0.60")
    assert result.signal.confidence <= Decimal("1")


def test_strategy_emits_short_for_confirmed_lower_value_breakout() -> None:
    candles = (
        make_candle(0, low="100", high="100", close="100", volume="10"),
        make_candle(1, low="101", high="101", close="101", volume="30"),
        make_candle(2, low="102", high="102", close="102", volume="10"),
        make_candle(3, low="99", high="99", close="99", volume="80"),
    )

    result = SessionVolumeProfileStrategy(
        price_bin_size=Decimal("1"),
        breakout_volume_multiplier=Decimal("1.20"),
    ).evaluate(make_context(candles))

    assert result.signal.direction is SignalDirection.SHORT
    assert result.signal.reasons[0].code == "lower_value_breakout"
    assert result.metadata["decision_type"] == "lower_breakout"


def test_strategy_waits_for_unconfirmed_breakout_volume() -> None:
    candles = (
        make_candle(0, low="100", high="100", close="100", volume="10"),
        make_candle(1, low="101", high="101", close="101", volume="30"),
        make_candle(2, low="102", high="102", close="102", volume="10"),
        make_candle(3, low="103", high="103", close="103", volume="5"),
    )

    result = SessionVolumeProfileStrategy(
        price_bin_size=Decimal("1"),
        breakout_volume_multiplier=Decimal("1.20"),
    ).evaluate(make_context(candles))

    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["decision_type"] == "wait"
    assert result.signal.metadata["reason"] == "unconfirmed_breakout_volume"


def test_strategy_waits_when_latest_candle_spans_both_value_area_boundaries() -> None:
    candles = (
        make_candle(0, low="100", high="100", close="100", volume="20"),
        make_candle(1, low="101", high="101", close="101", volume="30"),
        make_candle(2, low="102", high="102", close="102", volume="20"),
        make_candle(3, low="99", high="103", open_price="100", close="101", volume="12"),
    )

    result = SessionVolumeProfileStrategy(
        price_bin_size=Decimal("1"),
        rejection_wick_ratio=Decimal("0.20"),
    ).evaluate(make_context(candles))

    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["decision_type"] == "wait"
    assert result.signal.metadata["reason"] == "ambiguous_value_area_overlap"


def test_strategy_validates_profile_configuration() -> None:
    with pytest.raises(ValueError, match="price_bin_size"):
        SessionVolumeProfileStrategy(price_bin_size=Decimal("0"))

    with pytest.raises(ValueError, match="value_area_ratio"):
        SessionVolumeProfileStrategy(value_area_ratio=Decimal("1.1"))


def test_session_volume_profile_strategy_satisfies_strategy_protocol() -> None:
    strategy = SessionVolumeProfileStrategy(price_bin_size=Decimal("1"))

    assert isinstance(strategy, Strategy)
