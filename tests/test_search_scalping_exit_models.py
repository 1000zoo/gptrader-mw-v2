import pytest

from scripts.search_scalping_exit_models import (
    ExitCandidate,
    OpenPosition,
    close_position,
    partial_trailing_exit,
    stop_take_exit,
    time_exit,
)


def test_stop_take_exit_prefers_stop_when_same_long_candle_hits_both() -> None:
    position = OpenPosition(
        direction=1,
        entry_price=100.0,
        entry_index=1,
        notional=1000.0,
        margin=200.0,
    )
    data = {"high": [100.0, 102.0], "low": [100.0, 98.0], "close": [100.0, 101.0]}

    exit_price, reason = stop_take_exit(position, data, 1, tp=0.01, sl=0.01)

    assert reason == "stop_loss"
    assert exit_price == pytest.approx(98.9802)


def test_time_exit_closes_after_max_holding_minutes() -> None:
    candidate = ExitCandidate(
        candidate_id="time",
        kind="time",
        params={"max_holding_minutes": 3},
        filters={},
    )
    position = OpenPosition(
        direction=-1,
        entry_price=100.0,
        entry_index=2,
        notional=1000.0,
        margin=200.0,
    )
    data = {"close": [100.0, 100.0, 100.0, 100.0, 99.0, 98.0]}

    exit_price, reason = time_exit(candidate, position, data, 5)

    assert reason == "time_exit"
    assert exit_price == pytest.approx(98.0196)


def test_partial_trailing_realizes_first_take_profit_then_closes_remainder() -> None:
    candidate = ExitCandidate(
        candidate_id="partial",
        kind="partial_trailing",
        params={"sl": 0.02, "first_tp": 0.01, "partial_ratio": 0.5, "trail": 0.005},
        filters={},
    )
    position = OpenPosition(
        direction=1,
        entry_price=100.0,
        entry_index=1,
        notional=1000.0,
        margin=200.0,
    )
    data = {
        "high": [100.0, 101.5, 102.0],
        "low": [100.0, 100.5, 101.0],
        "close": [100.0, 101.0, 101.5],
    }

    assert partial_trailing_exit(candidate, position, data, 1) is None
    exit_price, reason = partial_trailing_exit(candidate, position, data, 2)
    trade = close_position(position, exit_price, reason)

    assert position.partial_done is True
    assert position.remaining_ratio == pytest.approx(0.5)
    assert reason == "partial_trailing_exit"
    assert trade["net_pnl"] > 0
    assert trade["fee_paid"] == pytest.approx(0.8)
