from src.strategy.strategies.models import StrategyInitConfig, StrategyRunInput
from src.strategy.strategies.volatility_breakout_regime_strategy import VolatilityBreakoutRegimeStrategy


def _build_input(*, ema_fast, ema_slow, adx, atr, rsi, bb_upper, bb_middle, bb_lower, close, volume):
    return StrategyRunInput(
        indicators_by_tf={
            "5m": [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "ema_fast": ema_fast,
                    "ema_slow": ema_slow,
                    "dmi_adx": adx,
                    "atr": atr,
                    "rsi": rsi,
                    "bollinger_upper": bb_upper,
                    "bollinger_mid": bb_middle,
                    "bollinger_lower": bb_lower,
                }
            ]
        },
        ohlcv_by_tf={
            "5m": {
                "timestamp": "2026-01-01T00:00:00Z",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": volume,
            }
        },
    )


def _build_strategy() -> VolatilityBreakoutRegimeStrategy:
    strategy = VolatilityBreakoutRegimeStrategy()
    strategy.init_strategy(
        StrategyInitConfig(
            strategy_name="vol_breakout",
            symbol="BTCUSDT",
            timeframes=["5m"],
            lookback_by_tf={"5m": 1},
            params={},
        )
    )
    return strategy


def test_run_strategy_returns_sell_on_short_entry_signal():
    strategy = _build_strategy()
    data = _build_input(
        ema_fast=95.0,
        ema_slow=100.0,
        adx=25.0,
        atr=0.7,
        rsi=60.0,
        bb_upper=100.0,
        bb_middle=98.0,
        bb_lower=96.0,
        close=101.0,
        volume=1000.0,
    )

    decision = strategy.run_strategy(data)

    assert decision.action == "SELL"
    assert decision.reason == "vol_breakout_short"


def test_run_strategy_returns_buy_on_long_entry_signal():
    strategy = _build_strategy()
    data = _build_input(
        ema_fast=105.0,
        ema_slow=100.0,
        adx=24.0,
        atr=0.8,
        rsi=40.0,
        bb_upper=104.0,
        bb_middle=102.0,
        bb_lower=100.0,
        close=99.0,
        volume=1500.0,
    )

    decision = strategy.run_strategy(data)

    assert decision.action == "BUY"
    assert decision.reason == "vol_breakout_long"


def test_run_strategy_returns_hold_when_no_entry_signal():
    strategy = _build_strategy()
    data = _build_input(
        ema_fast=100.0,
        ema_slow=100.0,
        adx=15.0,
        atr=0.1,
        rsi=50.0,
        bb_upper=102.0,
        bb_middle=100.0,
        bb_lower=98.0,
        close=100.0,
        volume=1000.0,
    )

    decision = strategy.run_strategy(data)

    assert decision.action == "HOLD"
    assert decision.reason == "no_entry_signal"


def test_run_exit_strategy_returns_sell_for_long_exit_signal():
    strategy = _build_strategy()
    data = _build_input(
        ema_fast=100.0,
        ema_slow=105.0,
        adx=20.0,
        atr=0.3,
        rsi=40.0,
        bb_upper=110.0,
        bb_middle=105.0,
        bb_lower=95.0,
        close=99.0,
        volume=1200.0,
    )

    decision = strategy.run_exit_strategy(data)

    assert decision.action == "SELL"
    assert decision.reason == "exit_long_signal"


def test_run_exit_strategy_returns_hold_when_keep_position():
    strategy = _build_strategy()
    data = _build_input(
        ema_fast=106.0,
        ema_slow=100.0,
        adx=20.0,
        atr=0.3,
        rsi=52.0,
        bb_upper=110.0,
        bb_middle=105.0,
        bb_lower=95.0,
        close=108.0,
        volume=1200.0,
    )

    decision = strategy.run_exit_strategy(data)

    assert decision.action == "HOLD"
    assert decision.reason == "keep_position"
