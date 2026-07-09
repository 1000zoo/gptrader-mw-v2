from datetime import datetime, timezone
from decimal import Decimal

from scripts.render_adopted_strategy_backtest_chart import (
    ADOPTED_COMBO_ID,
    adopted_combo,
    trade_record,
)
from src.application.usecases.research.dto import BacktestTrade
from src.domain.signal import SignalDirection


def test_adopted_combo_matches_selected_practical_strategy() -> None:
    combo = adopted_combo()

    assert combo.combo_id == ADOPTED_COMBO_ID
    assert combo.strategy_params == {
        "lookback": 180,
        "compression_period": 45,
        "compression_ratio": Decimal("0.45"),
        "breakout_buffer": Decimal("0.0006"),
        "min_volume_ratio": Decimal("1.00"),
        "direction_filter_period": 1440,
        "min_filter_return": Decimal("0.002"),
    }
    assert combo.tpsl_params == {
        "kind": "fixed",
        "stop_loss_ratio": Decimal("0.030"),
        "reward_risk_ratio": Decimal("0.45"),
    }
    assert combo.position_sizing_params["max_equity_ratio"] == Decimal("0.14")
    assert combo.position_sizing_params["max_leverage"] == Decimal("8")


def test_trade_record_includes_entry_exit_and_return_details() -> None:
    trade = BacktestTrade(
        direction=SignalDirection.LONG,
        entry_price=Decimal("100"),
        exit_price=Decimal("102"),
        quantity=Decimal("3"),
        gross_pnl=Decimal("6"),
        fee_paid=Decimal("0.24"),
        net_pnl=Decimal("5.76"),
        entry_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
        exit_time=datetime(2026, 5, 2, tzinfo=timezone.utc),
        exit_reason="take_profit",
    )

    record = trade_record(7, trade)

    assert record["trade_no"] == 7
    assert record["direction"] == "LONG"
    assert record["entry_time"] == "2026-05-01T00:00:00+00:00"
    assert record["exit_time"] == "2026-05-02T00:00:00+00:00"
    assert record["return_ratio"] == "0.0192"
    assert record["exit_reason"] == "take_profit"
