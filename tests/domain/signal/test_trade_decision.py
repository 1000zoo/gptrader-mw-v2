from decimal import Decimal

import pytest

from src.domain.signal import (
    Signal,
    SignalDirection,
    TradeDecision,
    TradeDecisionAction,
)


def test_trade_decision_keeps_final_action_and_source_signal():
    signal = Signal(direction=SignalDirection.LONG, confidence=Decimal("0.8"))

    decision = TradeDecision(action=TradeDecisionAction.ENTER_LONG, signal=signal)

    assert decision.action is TradeDecisionAction.ENTER_LONG
    assert decision.signal == signal


def test_trade_decision_rejects_long_entry_from_short_signal():
    signal = Signal(direction=SignalDirection.SHORT, confidence=Decimal("0.8"))

    with pytest.raises(ValueError, match="ENTER_LONG"):
        TradeDecision(action=TradeDecisionAction.ENTER_LONG, signal=signal)


def test_trade_decision_hold_accepts_wait_signal():
    signal = Signal.wait()

    decision = TradeDecision(action=TradeDecisionAction.HOLD, signal=signal)

    assert decision.action is TradeDecisionAction.HOLD
    assert decision.signal.direction is SignalDirection.WAIT
