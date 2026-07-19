from decimal import Decimal

import pytest

from src.domain.signal import Signal, SignalDirection, SignalReason


def test_signal_represents_direction_confidence_reasons_and_metadata():
    reason = SignalReason(code="breakout", message="Breakout confirmed")

    signal = Signal(
        direction=SignalDirection.LONG,
        confidence=Decimal("0.72"),
        reasons=(reason,),
        metadata={"strategy": "breakout_v1"},
    )

    assert signal.direction is SignalDirection.LONG
    assert signal.confidence == Decimal("0.72")
    assert signal.reasons == (reason,)
    assert signal.metadata["strategy"] == "breakout_v1"


def test_signal_requires_confidence_between_zero_and_one():
    with pytest.raises(ValueError, match="confidence"):
        Signal(direction=SignalDirection.SHORT, confidence=Decimal("1.01"))


def test_signal_wait_creates_non_entry_state_without_reasons():
    signal = Signal.wait(metadata={"cycle": "no_setup"})

    assert signal.direction is SignalDirection.WAIT
    assert signal.confidence == Decimal("0")
    assert signal.reasons == ()
    assert signal.metadata["cycle"] == "no_setup"


def test_signal_copies_reasons_and_metadata():
    reasons = [SignalReason(code="range", message="Range-bound market")]
    metadata = {"source": "strategy_a"}

    signal = Signal(
        direction=SignalDirection.WAIT,
        confidence=Decimal("0.4"),
        reasons=reasons,
        metadata=metadata,
    )

    reasons.append(SignalReason(code="late", message="Late reason"))
    metadata["source"] = "changed"

    assert len(signal.reasons) == 1
    assert signal.metadata["source"] == "strategy_a"
