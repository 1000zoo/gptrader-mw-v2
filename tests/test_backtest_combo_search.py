from decimal import Decimal

from scripts.backtest_combo_search import (
    Combo,
    FixedRatioTakeProfitStopLossStrategy,
    run_combo,
    target_met,
)
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.risk import FixedPositionSizingStrategy
from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import StrategyContext, StrategyResult
from datetime import datetime, timedelta, timezone


class AlwaysLongStrategy:
    def evaluate(self, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            name="always-long",
            signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
        )


def _market() -> MarketSnapshot:
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    start = datetime(2026, 1, 9, 0, 0, tzinfo=timezone.utc)
    candles = []
    for index, close in enumerate((Decimal("100"), Decimal("110"))):
        opened_at = start + timedelta(minutes=index)
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                opened_at=opened_at,
                closed_at=opened_at + timedelta(minutes=1),
                open_price=close,
                high_price=close,
                low_price=close,
                close_price=close,
                volume=Decimal("1"),
            )
        )
    return MarketSnapshot(tuple(candles))


def test_target_requires_minimum_trade_count() -> None:
    result = {
        "trade_count": 1,
        "win_rate": "1",
        "average_trade_return": "0.02",
    }

    assert not target_met(
        result,
        min_win_rate=Decimal("0.60"),
        min_average_trade_return=Decimal("0.005"),
        min_trade_count=100,
    )


def test_target_passes_when_return_win_rate_and_trade_count_pass() -> None:
    result = {
        "trade_count": 100,
        "win_rate": "0.61",
        "average_trade_return": "0.0051",
    }

    assert target_met(
        result,
        min_win_rate=Decimal("0.60"),
        min_average_trade_return=Decimal("0.005"),
        min_trade_count=100,
    )


def test_run_combo_records_and_uses_position_sizing_strategy() -> None:
    combo = Combo(
        combo_id="position-sizing-smoke",
        strategy_factory=AlwaysLongStrategy,
        strategy_params={},
        tpsl_factory=lambda: FixedRatioTakeProfitStopLossStrategy(
            stop_loss_ratio=Decimal("0.05"),
            reward_risk_ratio=Decimal("2"),
        ),
        tpsl_params={
            "kind": "fixed",
            "stop_loss_ratio": Decimal("0.05"),
            "reward_risk_ratio": Decimal("2"),
        },
        position_sizing_factory=lambda: FixedPositionSizingStrategy(
            equity_ratio=Decimal("0.25"),
            leverage=Decimal("4"),
        ),
        position_sizing_params={
            "kind": "fixed",
            "equity_ratio": Decimal("0.25"),
            "leverage": Decimal("4"),
        },
    )

    result = run_combo(_market(), combo)

    assert Decimal(str(result["return_ratio"])) == Decimal("0.1")
    assert result["position_sizing_params"] == {
        "kind": "fixed",
        "equity_ratio": "0.25",
        "leverage": "4",
    }
