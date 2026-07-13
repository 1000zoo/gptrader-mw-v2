from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.domain.indicator import IndicatorSet
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.signal import SignalDirection
from src.domain.strategy import StrategyContext
from src.domain.strategy.implementations.regime_router_scalper_strategy import (
    BreakoutRetestContinuationScalper,
    ImpulsePullbackContinuationScalper,
    LiquiditySweepReversalScalper,
    RegimeRouterScalperStrategy,
    ThreePushExhaustionReversalScalper,
    VolumeDryUpBreakoutScalper,
    VolatilityExpansionContinuationScalper,
)


SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")


def test_impulse_pullback_continuation_signals_long_after_resume() -> None:
    candles = _candles(
        Decimal("100"),
        [Decimal("0")] * 10
        + [Decimal("0.008")]
        + [Decimal("-0.0015"), Decimal("-0.0010"), Decimal("-0.0008")]
        + [Decimal("0.0025")],
    )

    result = ImpulsePullbackContinuationScalper(
        impulse_period=1,
        pullback_period=3,
        trigger_period=1,
        min_impulse_return=Decimal("0.006"),
        min_pullback=Decimal("0.002"),
        min_resume_return=Decimal("0.0015"),
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.LONG


def test_breakout_retest_continuation_signals_long_after_level_reclaim() -> None:
    candles = _flat_level_candles(Decimal("100"), count=30)
    candles = candles + _candles_from(
        candles[-1],
        [
            (Decimal("100"), Decimal("103"), Decimal("99.8"), Decimal("102.5")),
            (Decimal("102.5"), Decimal("102.8"), Decimal("100.1"), Decimal("100.5")),
            (Decimal("100.5"), Decimal("102.2"), Decimal("100.4"), Decimal("101.8")),
        ],
    )

    result = BreakoutRetestContinuationScalper(
        breakout_period=30,
        retest_period=2,
        breakout_buffer=Decimal("0.002"),
        retest_tolerance=Decimal("0.003"),
        min_reclaim_return=Decimal("0.001"),
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.LONG


def test_volatility_expansion_continuation_requires_range_and_volume_expansion() -> None:
    candles = _quiet_candles(Decimal("100"), count=30)
    latest = candles[-1]
    candles = candles[:-1] + (
        Candle(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            opened_at=latest.opened_at,
            closed_at=latest.closed_at,
            open_price=Decimal("100"),
            high_price=Decimal("101.4"),
            low_price=Decimal("99.9"),
            close_price=Decimal("101.2"),
            volume=Decimal("260"),
        ),
    )

    result = VolatilityExpansionContinuationScalper(
        range_period=20,
        volume_period=20,
        min_range_expansion=Decimal("2.0"),
        min_volume_ratio=Decimal("2.0"),
        min_body_ratio=Decimal("0.60"),
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.LONG


def test_liquidity_sweep_reversal_signals_long_after_failed_low_break() -> None:
    candles = _flat_level_candles(Decimal("100"), count=30)
    latest = candles[-1]
    candles = candles[:-1] + (
        Candle(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            opened_at=latest.opened_at,
            closed_at=latest.closed_at,
            open_price=Decimal("99.4"),
            high_price=Decimal("100.2"),
            low_price=Decimal("98.7"),
            close_price=Decimal("99.9"),
            volume=Decimal("240"),
        ),
    )

    result = LiquiditySweepReversalScalper(
        lookback_period=20,
        sweep_buffer=Decimal("0.001"),
        min_close_reclaim=Decimal("0.0005"),
        min_wick_ratio=Decimal("0.40"),
        volume_period=20,
        min_volume_ratio=Decimal("1.5"),
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.LONG


def test_volume_dryup_breakout_signals_after_quiet_range_break() -> None:
    candles = tuple(
        candle if index < 26 else _with_volume(candle, Decimal("50"))
        for index, candle in enumerate(_quiet_candles(Decimal("100"), count=35))
    )
    latest = candles[-1]
    candles = candles[:-1] + (
        Candle(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            opened_at=latest.opened_at,
            closed_at=latest.closed_at,
            open_price=Decimal("100"),
            high_price=Decimal("101.8"),
            low_price=Decimal("99.9"),
            close_price=Decimal("101.5"),
            volume=Decimal("220"),
        ),
    )

    result = VolumeDryUpBreakoutScalper(
        range_period=20,
        dryup_period=8,
        volume_period=20,
        max_dryup_volume_ratio=Decimal("0.9"),
        min_breakout_volume_ratio=Decimal("1.6"),
        breakout_buffer=Decimal("0.001"),
        min_body_ratio=Decimal("0.50"),
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.LONG


def test_three_push_exhaustion_reversal_signals_short_after_extended_rise_rejection() -> None:
    candles = _candles(
        Decimal("100"),
        [Decimal("0.0015")] * 35 + [Decimal("-0.0005"), Decimal("0.0010")],
    )
    latest = candles[-1]
    candles = candles[:-1] + (
        Candle(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            opened_at=latest.opened_at,
            closed_at=latest.closed_at,
            open_price=latest.open_price,
            high_price=latest.open_price * Decimal("1.018"),
            low_price=latest.open_price * Decimal("0.998"),
            close_price=latest.open_price * Decimal("1.002"),
            volume=Decimal("260"),
        ),
    )

    result = ThreePushExhaustionReversalScalper(
        trend_period=30,
        min_trend_return=Decimal("0.035"),
        push_lookback=12,
        min_new_extremes=3,
        min_rejection_wick_ratio=Decimal("0.55"),
        volume_period=20,
        min_volume_ratio=Decimal("1.8"),
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.SHORT


def test_regime_router_can_route_to_new_alpha_entry() -> None:
    candles = _candles(
        Decimal("100"),
        [Decimal("0")] * 250
        + [Decimal("0.008")]
        + [Decimal("-0.0015"), Decimal("-0.0010"), Decimal("-0.0008")]
        + [Decimal("0.0025")],
    )

    result = RegimeRouterScalperStrategy(
        router_order=("impulse_pullback",),
        impulse_pullback_params={
            "impulse_period": 1,
            "pullback_period": 3,
            "trigger_period": 1,
            "min_impulse_return": Decimal("0.006"),
            "min_pullback": Decimal("0.002"),
            "min_resume_return": Decimal("0.0015"),
        },
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.LONG


def test_regime_router_can_route_to_liquidity_sweep_alpha() -> None:
    candles = _flat_level_candles(Decimal("100"), count=260)
    latest = candles[-1]
    candles = candles[:-1] + (
        Candle(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            opened_at=latest.opened_at,
            closed_at=latest.closed_at,
            open_price=Decimal("99.4"),
            high_price=Decimal("100.2"),
            low_price=Decimal("98.7"),
            close_price=Decimal("99.9"),
            volume=Decimal("240"),
        ),
    )

    result = RegimeRouterScalperStrategy(
        router_order=("liquidity_sweep",),
        liquidity_sweep_params={
            "lookback_period": 20,
            "sweep_buffer": Decimal("0.001"),
            "min_close_reclaim": Decimal("0.0005"),
            "min_wick_ratio": Decimal("0.40"),
            "volume_period": 20,
            "min_volume_ratio": Decimal("1.5"),
        },
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.LONG


def _context(candles) -> StrategyContext:
    return StrategyContext(
        market=MarketSnapshot(tuple(candles)),
        indicators=IndicatorSet(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            measured_at=candles[-1].closed_at,
            values=(),
        ),
    )


def _candles(start_price: Decimal, returns):
    opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = start_price
    candles = []
    for index, return_ratio in enumerate(returns):
        open_price = price
        close_price = price * (Decimal("1") + return_ratio)
        high_price = max(open_price, close_price) * Decimal("1.001")
        low_price = min(open_price, close_price) * Decimal("0.999")
        candles.append(
            Candle(
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                opened_at=opened_at + timedelta(minutes=index),
                closed_at=opened_at + timedelta(minutes=index + 1),
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=Decimal("100"),
            )
        )
        price = close_price
    return tuple(candles)


def _flat_level_candles(price: Decimal, *, count: int):
    opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return tuple(
        Candle(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            opened_at=opened_at + timedelta(minutes=index),
            closed_at=opened_at + timedelta(minutes=index + 1),
            open_price=price,
            high_price=price,
            low_price=price * Decimal("0.998"),
            close_price=price * Decimal("0.999"),
            volume=Decimal("100"),
        )
        for index in range(count)
    )


def _candles_from(previous: Candle, ohlc_values):
    candles = []
    for offset, (open_price, high_price, low_price, close_price) in enumerate(ohlc_values, start=1):
        candles.append(
            Candle(
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                opened_at=previous.opened_at + timedelta(minutes=offset),
                closed_at=previous.closed_at + timedelta(minutes=offset),
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=Decimal("120"),
            )
        )
    return tuple(candles)


def _quiet_candles(price: Decimal, *, count: int):
    opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return tuple(
        Candle(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            opened_at=opened_at + timedelta(minutes=index),
            closed_at=opened_at + timedelta(minutes=index + 1),
            open_price=price,
            high_price=price * Decimal("1.001"),
            low_price=price * Decimal("0.999"),
            close_price=price,
            volume=Decimal("100"),
        )
        for index in range(count)
    )


def _with_volume(candle: Candle, volume: Decimal) -> Candle:
    return Candle(
        symbol=candle.symbol,
        timeframe=candle.timeframe,
        opened_at=candle.opened_at,
        closed_at=candle.closed_at,
        open_price=candle.open_price,
        high_price=candle.high_price,
        low_price=candle.low_price,
        close_price=candle.close_price,
        volume=volume,
    )
