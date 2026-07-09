from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.domain.indicator import IndicatorSet
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.signal import SignalDirection
from src.domain.strategy import StrategyContext
from src.domain.strategy.implementations import (
    ChartPatternStrategy,
    PivotDetector,
    create_default_strategy_catalog,
)


SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")


def make_market(values: tuple[tuple[str, str, str, str, str], ...]) -> MarketSnapshot:
    start = datetime(2026, 7, 7, 0, 0, tzinfo=timezone.utc)
    candles = []
    for index, (open_price, high, low, close, volume) in enumerate(values):
        opened_at = start + timedelta(minutes=index)
        candles.append(
            Candle(
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                opened_at=opened_at,
                closed_at=opened_at + timedelta(minutes=1),
                open_price=Decimal(open_price),
                high_price=Decimal(high),
                low_price=Decimal(low),
                close_price=Decimal(close),
                volume=Decimal(volume),
            )
        )
    return MarketSnapshot(tuple(candles))


def make_context(market: MarketSnapshot) -> StrategyContext:
    return StrategyContext(
        market=market,
        indicators=IndicatorSet(
            symbol=market.symbol,
            timeframe=market.timeframe,
            measured_at=market.latest_candle.closed_at,
            values=(),
        ),
    )


def test_pivot_detector_finds_local_highs_and_lows() -> None:
    market = make_market(
        (
            ("10", "11", "9", "10", "10"),
            ("10", "15", "8", "11", "10"),
            ("11", "12", "10", "11", "10"),
            ("11", "13", "7", "10", "10"),
            ("10", "11", "8", "10", "10"),
        )
    )

    highs = PivotDetector.find_pivot_highs(market.candles, pivot_window=1)
    lows = PivotDetector.find_pivot_lows(market.candles, pivot_window=1)

    assert [pivot.index for pivot in highs] == [1, 3]
    assert [pivot.index for pivot in lows] == [1, 3]


def test_chart_pattern_strategy_emits_buy_on_ascending_triangle_breakout() -> None:
    market = make_market(
        (
            ("95", "100", "90", "96", "10"),
            ("96", "112", "96", "108", "10"),
            ("108", "109", "94", "100", "10"),
            ("100", "111", "98", "107", "10"),
            ("107", "108", "96", "103", "10"),
            ("103", "113", "102", "112.5", "20"),
        )
    )

    result = ChartPatternStrategy(
        lookback=20,
        pivot_window=1,
        price_tolerance=Decimal("0.02"),
        volume_ma_period=3,
        volume_multiplier=Decimal("1.1"),
    ).evaluate(make_context(market))

    assert result.name == "chart-pattern"
    assert result.signal.direction is SignalDirection.LONG
    assert result.metadata["strategy"] == "chart_pattern"
    assert result.metadata["signal"] == "BUY"
    assert result.metadata["pattern"] == "ascending_triangle"
    assert result.metadata["entry_price"] == Decimal("112.5")
    assert result.metadata["stop_loss"] is not None
    assert result.metadata["take_profit"] is not None


def test_chart_pattern_strategy_emits_sell_on_double_top_neckline_breakdown() -> None:
    market = make_market(
        (
            ("100", "102", "95", "98", "10"),
            ("106", "120", "105", "116", "10"),
            ("116", "117", "100", "104", "10"),
            ("104", "119", "103", "116", "10"),
            ("116", "117", "96", "98", "20"),
        )
    )

    result = ChartPatternStrategy(
        lookback=20,
        pivot_window=1,
        price_tolerance=Decimal("0.02"),
        volume_ma_period=3,
        volume_multiplier=Decimal("1.1"),
    ).evaluate(make_context(market))

    assert result.signal.direction is SignalDirection.SHORT
    assert result.metadata["signal"] == "SELL"
    assert result.metadata["pattern"] == "double_top"


def test_chart_pattern_strategy_holds_while_pattern_is_forming() -> None:
    market = make_market(
        (
            ("95", "100", "90", "96", "10"),
            ("96", "112", "96", "108", "10"),
            ("108", "109", "94", "100", "10"),
            ("100", "111", "98", "107", "10"),
            ("107", "108", "96", "108", "10"),
            ("108", "110", "100", "110", "10"),
        )
    )

    result = ChartPatternStrategy(
        lookback=20,
        pivot_window=1,
        price_tolerance=Decimal("0.02"),
    ).evaluate(make_context(market))

    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["signal"] == "HOLD"
    assert result.metadata["pattern"] == "ascending_triangle"


def test_chart_pattern_strategy_holds_when_confidence_is_below_minimum() -> None:
    market = make_market(
        (
            ("95", "100", "90", "96", "10"),
            ("96", "112", "96", "108", "10"),
            ("108", "109", "94", "100", "10"),
            ("100", "111", "98", "107", "10"),
            ("107", "108", "96", "103", "10"),
            ("103", "113", "102", "112.5", "10"),
        )
    )

    result = ChartPatternStrategy(
        lookback=20,
        pivot_window=1,
        price_tolerance=Decimal("0.02"),
        volume_ma_period=3,
        volume_multiplier=Decimal("3"),
        min_confidence=Decimal("0.95"),
    ).evaluate(make_context(market))

    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["signal"] == "HOLD"
    assert result.metadata["pattern"] == "ascending_triangle"


def test_default_strategy_catalog_can_enable_chart_pattern_strategy() -> None:
    catalog = create_default_strategy_catalog()
    specs = {spec.strategy_id: spec for spec in catalog.list_specs()}

    strategy = catalog.create_strategy(specs["chart-pattern"])

    assert isinstance(strategy, ChartPatternStrategy)
    assert specs["chart-pattern"].metadata["family"] == "chart_pattern"
    assert specs["chart-pattern"].parameters["lookback"] == 120
