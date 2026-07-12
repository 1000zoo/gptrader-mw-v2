from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.domain.indicator import IndicatorSet, IndicatorValue
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.market_feature import MARKET_FEATURES_METADATA_KEY, MarketFeatureSet
from src.domain.strategy import StrategyContext


def make_candle(
    opened_at: datetime,
    symbol: Symbol | None = None,
    timeframe: Timeframe | None = None,
) -> Candle:
    candle_timeframe = timeframe or Timeframe(1, "m")
    return Candle(
        symbol=symbol or Symbol("BTC", "USDT"),
        timeframe=candle_timeframe,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(seconds=candle_timeframe.duration_seconds),
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("105"),
        volume=Decimal("1"),
    )


def make_market(
    symbol: Symbol | None = None,
    timeframe: Timeframe | None = None,
) -> MarketSnapshot:
    opened_at = datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc)
    return MarketSnapshot(candles=(make_candle(opened_at, symbol, timeframe),))


def make_indicators(
    market: MarketSnapshot,
    symbol: Symbol | None = None,
    timeframe: Timeframe | None = None,
    measured_at: datetime | None = None,
) -> IndicatorSet:
    return IndicatorSet(
        symbol=symbol or market.symbol,
        timeframe=timeframe or market.timeframe,
        measured_at=measured_at or market.latest_candle.closed_at,
        values=(
            IndicatorValue(
                name="rsi",
                value=Decimal("52.1"),
                measured_at=measured_at or market.latest_candle.closed_at,
            ),
        ),
    )


def test_strategy_context_accepts_matching_market_and_indicators():
    market = make_market()
    indicators = make_indicators(market)

    context = StrategyContext(
        market=market,
        indicators=indicators,
        metadata={"regime": "trend"},
    )

    assert context.market == market
    assert context.indicators == indicators
    assert context.metadata["regime"] == "trend"


def test_strategy_context_rejects_mismatched_symbol():
    market = make_market()
    indicators = make_indicators(market, symbol=Symbol("ETH", "USDT"))

    with pytest.raises(ValueError, match="symbol"):
        StrategyContext(market=market, indicators=indicators)


def test_strategy_context_rejects_mismatched_timeframe():
    market = make_market()
    indicators = make_indicators(market, timeframe=Timeframe(5, "m"))

    with pytest.raises(ValueError, match="timeframe"):
        StrategyContext(market=market, indicators=indicators)


def test_strategy_context_rejects_indicators_for_different_latest_candle_time():
    market = make_market()
    measured_at = market.latest_candle.closed_at + timedelta(minutes=1)
    indicators = make_indicators(market, measured_at=measured_at)

    with pytest.raises(ValueError, match="measured_at"):
        StrategyContext(market=market, indicators=indicators)


def test_strategy_context_defensively_copies_metadata():
    market = make_market()
    metadata = {"regime": "trend"}

    context = StrategyContext(
        market=market,
        indicators=make_indicators(market),
        metadata=metadata,
    )
    metadata["regime"] = "range"

    assert context.metadata["regime"] == "trend"
    with pytest.raises(TypeError):
        context.metadata["regime"] = "range"


def test_strategy_context_returns_aligned_market_features_from_metadata():
    market = make_market()
    features = MarketFeatureSet(
        market.symbol,
        market.timeframe,
        market.latest_candle.closed_at,
        (),
    )

    context = StrategyContext(
        market=market,
        indicators=make_indicators(market),
        metadata={MARKET_FEATURES_METADATA_KEY: features},
    )

    assert context.market_features is features


def test_strategy_context_returns_none_without_market_features_metadata():
    market = make_market()

    context = StrategyContext(market=market, indicators=make_indicators(market))

    assert context.market_features is None


def test_strategy_context_rejects_explicit_none_market_features_metadata():
    market = make_market()

    with pytest.raises(TypeError, match="MarketFeatureSet"):
        StrategyContext(
            market=market,
            indicators=make_indicators(market),
            metadata={MARKET_FEATURES_METADATA_KEY: None},
        )


@pytest.mark.parametrize(
    ("features", "message"),
    [
        ("not-features", "MarketFeatureSet"),
        (
            MarketFeatureSet(
                Symbol("ETH", "USDT"),
                Timeframe(1, "m"),
                datetime(2026, 5, 24, 0, 1, tzinfo=timezone.utc),
                (),
            ),
            "symbol",
        ),
        (
            MarketFeatureSet(
                Symbol("BTC", "USDT"),
                Timeframe(5, "m"),
                datetime(2026, 5, 24, 0, 1, tzinfo=timezone.utc),
                (),
            ),
            "timeframe",
        ),
        (
            MarketFeatureSet(
                Symbol("BTC", "USDT"),
                Timeframe(1, "m"),
                datetime(2026, 5, 24, 0, 2, tzinfo=timezone.utc),
                (),
            ),
            "measured_at",
        ),
    ],
)
def test_strategy_context_rejects_invalid_market_features(features, message):
    market = make_market()

    with pytest.raises((TypeError, ValueError), match=message):
        StrategyContext(
            market=market,
            indicators=make_indicators(market),
            metadata={MARKET_FEATURES_METADATA_KEY: features},
        )
