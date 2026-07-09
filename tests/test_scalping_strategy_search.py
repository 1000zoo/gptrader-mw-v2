from datetime import datetime, timedelta, timezone
from decimal import Decimal

from scripts.scalping_train_test_combo_search import (
    TEST_DAYS,
    MomentumBurstScalper,
    RangeEdgeReversionScalper,
    TrendPullbackScalper,
    combine_result,
)
from src.domain.indicator import IndicatorSet
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.signal import SignalDirection
from src.domain.strategy import StrategyContext


SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")


def test_trend_pullback_scalper_signals_long_on_uptrend_pullback_resume() -> None:
    candles = _candles(
        Decimal("100"),
        [Decimal("0.001")] * 20
        + [Decimal("-0.001")] * 3
        + [Decimal("0.002")],
    )

    result = TrendPullbackScalper(
        trend_period=20,
        pullback_period=4,
        trigger_period=1,
        min_trend_return=Decimal("0.010"),
        min_pullback=Decimal("0.002"),
        min_trigger_return=Decimal("0.001"),
        min_range_ratio=Decimal("0"),
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.LONG


def test_range_edge_reversion_scalper_signals_short_near_range_high() -> None:
    candles = _flat_range_candles()
    latest = candles[-1]
    candles = candles[:-1] + (
        Candle(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            opened_at=latest.opened_at,
            closed_at=latest.closed_at,
            open_price=Decimal("111"),
            high_price=Decimal("111"),
            low_price=Decimal("106"),
            close_price=Decimal("109"),
            volume=Decimal("100"),
        ),
    )

    result = RangeEdgeReversionScalper(
        range_period=20,
        edge_ratio=Decimal("0.15"),
        min_reversal_body_ratio=Decimal("0.20"),
        min_range_ratio=Decimal("0.015"),
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.SHORT


def test_momentum_burst_scalper_signals_on_volume_breakout() -> None:
    candles = _candles(Decimal("100"), [Decimal("0")] * 21 + [Decimal("0.006")])
    latest = candles[-1]
    candles = candles[:-1] + (
        Candle(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            opened_at=latest.opened_at,
            closed_at=latest.closed_at,
            open_price=latest.open_price,
            high_price=latest.high_price,
            low_price=latest.low_price,
            close_price=latest.close_price,
            volume=Decimal("250"),
        ),
    )

    result = MomentumBurstScalper(
        breakout_period=20,
        impulse_period=1,
        volume_period=20,
        min_impulse_return=Decimal("0.004"),
        min_volume_ratio=Decimal("2"),
        breakout_buffer=Decimal("0"),
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.LONG


def test_combined_result_includes_test_trades_per_day() -> None:
    combined = combine_result(
        {"combo_id": "x", "trade_count": 100, "win_rate": "0.6", "return_ratio": "0.1", "net_pnl": "1", "max_drawdown_ratio": "0.01", "average_net_trade_return": "0.001", "gross_win_rate": "0.7", "average_gross_trade_return": "0.003", "average_gross_trade_roe": "0.006", "gross_pnl": "2", "fee_paid": "1", "strategy_params": {}, "tpsl_params": {}, "position_sizing_params": {}},
        {"combo_id": "x", "trade_count": 690, "win_rate": "0.6", "return_ratio": "0.1", "net_pnl": "1", "max_drawdown_ratio": "0.01", "average_net_trade_return": "0.001", "gross_win_rate": "0.7", "average_gross_trade_return": "0.003", "average_gross_trade_roe": "0.006", "gross_pnl": "2", "fee_paid": "1", "strategy_params": {}, "tpsl_params": {}, "position_sizing_params": {}},
    )

    assert Decimal(str(combined["test_trades_per_day"])).quantize(Decimal("0.01")) == (
        Decimal("690") / TEST_DAYS
    ).quantize(Decimal("0.01"))


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


def _flat_range_candles():
    opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return tuple(
        Candle(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            opened_at=opened_at + timedelta(minutes=index),
            closed_at=opened_at + timedelta(minutes=index + 1),
            open_price=Decimal("105"),
            high_price=Decimal("110"),
            low_price=Decimal("100"),
            close_price=Decimal("105"),
            volume=Decimal("100"),
        )
        for index in range(22)
    )
