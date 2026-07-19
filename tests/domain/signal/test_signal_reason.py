from decimal import Decimal

from src.domain.signal import SignalReason


def test_signal_reason_keeps_stable_code_message_and_metadata():
    reason = SignalReason(
        code="trend_breakout",
        message="Price closed above resistance",
        metadata={"resistance": Decimal("42000")},
    )

    assert reason.code == "trend_breakout"
    assert reason.message == "Price closed above resistance"
    assert reason.metadata["resistance"] == Decimal("42000")


def test_signal_reason_copies_metadata_to_prevent_external_mutation():
    metadata = {"source": "ema_cross"}
    reason = SignalReason(
        code="momentum",
        message="Fast EMA crossed slow EMA",
        metadata=metadata,
    )

    metadata["source"] = "changed"

    assert reason.metadata["source"] == "ema_cross"
