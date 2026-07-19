from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.domain.indicator import IndicatorSet
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.signal import SignalDirection
from src.domain.strategy import StrategyContext
from src.domain.strategy.implementations import (
    AtrTakeProfitStopLossStrategy,
    FixedRatioTakeProfitStopLossStrategy,
)


def _candle(index: int, high: str, low: str, close: str) -> Candle:
    timeframe = Timeframe(1, "m")
    opened_at = datetime(2026, 6, 21, 0, index, tzinfo=timezone.utc)
    return Candle(
        symbol=Symbol("BTC", "USDT"),
        timeframe=timeframe,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(seconds=timeframe.duration_seconds),
        open_price=Decimal(close),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
        volume=Decimal("1"),
    )


def _context() -> StrategyContext:
    market = MarketSnapshot(
        candles=(
            _candle(0, "110", "90", "100"),
            _candle(1, "112", "96", "108"),
            _candle(2, "115", "105", "110"),
            _candle(3, "120", "108", "118"),
        )
    )
    return StrategyContext(
        market=market,
        indicators=IndicatorSet(
            symbol=market.symbol,
            timeframe=market.timeframe,
            measured_at=market.latest_candle.closed_at,
            values=(),
        ),
    )


def test_atr_take_profit_stop_loss_strategy_calculates_long_levels():
    strategy = AtrTakeProfitStopLossStrategy(
        atr_period=3,
        atr_multiplier=Decimal("2"),
        reward_risk_ratio=Decimal("2"),
    )

    levels = strategy.calculate(_context(), SignalDirection.LONG)

    assert levels.strategy_name == "atr-take-profit-stop-loss"
    assert levels.entry_price == Decimal("118")
    assert levels.stop_loss == Decimal("92.66666666666666666666666666")
    assert levels.take_profit == Decimal("168.6666666666666666666666667")
    assert levels.metadata["atr"] == "12.66666666666666666666666667"


def test_atr_take_profit_stop_loss_strategy_calculates_short_levels():
    strategy = AtrTakeProfitStopLossStrategy(
        atr_period=3,
        atr_multiplier=Decimal("1.5"),
        reward_risk_ratio=Decimal("2"),
    )

    levels = strategy.calculate(_context(), SignalDirection.SHORT)

    assert levels.entry_price == Decimal("118")
    assert levels.stop_loss == Decimal("137.0000000000000000000000000")
    assert levels.take_profit == Decimal("80.0000000000000000000000000")


def test_atr_take_profit_stop_loss_strategy_rejects_wait_direction():
    strategy = AtrTakeProfitStopLossStrategy(atr_period=3)

    with pytest.raises(ValueError, match="direction"):
        strategy.calculate(_context(), SignalDirection.WAIT)


def test_atr_take_profit_stop_loss_strategy_requires_enough_candles():
    market = MarketSnapshot(candles=(_candle(0, "110", "90", "100"),))
    context = StrategyContext(
        market=market,
        indicators=IndicatorSet(
            symbol=market.symbol,
            timeframe=market.timeframe,
            measured_at=market.latest_candle.closed_at,
            values=(),
        ),
    )
    strategy = AtrTakeProfitStopLossStrategy(atr_period=3)

    with pytest.raises(ValueError, match="atr_period"):
        strategy.calculate(context, SignalDirection.LONG)


def test_fixed_ratio_take_profit_stop_loss_strategy_calculates_seed_combo_levels():
    strategy = FixedRatioTakeProfitStopLossStrategy(
        stop_loss_ratio=Decimal("0.09"),
        reward_risk_ratio=Decimal("0.15"),
    )

    levels = strategy.calculate(_context(), SignalDirection.LONG)

    assert levels.strategy_name == "fixed-ratio-take-profit-stop-loss"
    assert levels.entry_price == Decimal("118")
    assert levels.stop_loss == Decimal("107.38")
    assert levels.take_profit == Decimal("119.5930")
    assert levels.metadata == {
        "stop_loss_ratio": "0.09",
        "reward_risk_ratio": "0.15",
    }
