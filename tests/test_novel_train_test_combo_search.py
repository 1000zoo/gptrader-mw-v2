from decimal import Decimal

from scripts.novel_train_test_combo_search import (
    LiquiditySweepReclaimStrategy,
    QualityVolatilitySizingStrategy,
    TimeboxedTrendAccelerationStrategy,
    VolatilityCompressionBreakoutStrategy,
    build_novel_combos,
    filter_targets,
    gross_trade_metrics,
)
from src.application.usecases.research.dto import BacktestTrade
from src.domain.signal import SignalDirection


def test_build_novel_combos_uses_new_strategy_and_sizing_ideas() -> None:
    combos = build_novel_combos()

    strategy_factories = {combo.strategy_factory for combo in combos}
    sizing_factories = {combo.position_sizing_factory().__class__ for combo in combos}

    assert VolatilityCompressionBreakoutStrategy in strategy_factories
    assert LiquiditySweepReclaimStrategy in strategy_factories
    assert TimeboxedTrendAccelerationStrategy in strategy_factories
    assert QualityVolatilitySizingStrategy in sizing_factories
    assert all("novel-" in combo.combo_id for combo in combos)


def test_gross_trade_metrics_ignore_fee_paid_for_average_trade_return() -> None:
    trades = (
        BacktestTrade(
            direction=SignalDirection.LONG,
            entry_price=Decimal("100"),
            exit_price=Decimal("101"),
            quantity=Decimal("2"),
            gross_pnl=Decimal("2"),
            fee_paid=Decimal("10"),
            net_pnl=Decimal("-8"),
            entry_time=None,
            exit_time=None,
            exit_reason="take_profit",
        ),
    )

    metrics = gross_trade_metrics(trades)

    assert metrics["average_gross_trade_return"] == Decimal("0.01")
    assert metrics["gross_win_rate"] == Decimal("1")


def test_filter_targets_requires_train_thresholds_before_test_ranking() -> None:
    qualified = {
        "combo_id": "qualified",
        "train_win_rate": "0.80",
        "train_average_gross_trade_return": "0.006",
        "train_trade_count": 3,
        "test_return_ratio": "0.01",
        "test_win_rate": "0.50",
        "test_average_gross_trade_return": "0.001",
    }
    weak = {
        **qualified,
        "combo_id": "weak",
        "train_win_rate": "0.79",
        "test_return_ratio": "1",
    }

    assert filter_targets([weak, qualified]) == [qualified]
