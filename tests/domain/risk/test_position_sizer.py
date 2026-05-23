from decimal import Decimal

import pytest

from src.domain.risk import ExposureLimit, PositionSizer
from src.domain.signal import (
    Signal,
    SignalDirection,
    TradeDecision,
    TradeDecisionAction,
)


def _decision(confidence: str = "0.5") -> TradeDecision:
    return TradeDecision(
        action=TradeDecisionAction.ENTER_LONG,
        signal=Signal(direction=SignalDirection.LONG, confidence=Decimal(confidence)),
    )


def _limit() -> ExposureLimit:
    return ExposureLimit(
        equity=Decimal("1000"),
        current_total_exposure=Decimal("100"),
        current_symbol_exposure=Decimal("50"),
        max_total_exposure_ratio=Decimal("1"),
        max_symbol_exposure_ratio=Decimal("0.8"),
    )


def test_position_sizer_uses_confidence_based_notional():
    sizer = PositionSizer(base_risk_ratio=Decimal("0.1"), leverage=Decimal("3"))

    size = sizer.size(
        decision=_decision(confidence="0.5"),
        exposure_limit=_limit(),
        entry_price=Decimal("30"),
    )

    assert size.notional == Decimal("150.00")
    assert size.quantity == Decimal("5.00")


def test_position_sizer_caps_notional_by_remaining_exposure():
    sizer = PositionSizer(base_risk_ratio=Decimal("0.5"), leverage=Decimal("4"))
    limit = ExposureLimit(
        equity=Decimal("1000"),
        current_total_exposure=Decimal("100"),
        current_symbol_exposure=Decimal("740"),
        max_total_exposure_ratio=Decimal("2"),
        max_symbol_exposure_ratio=Decimal("0.8"),
    )

    size = sizer.size(
        decision=_decision(confidence="1"),
        exposure_limit=limit,
        entry_price=Decimal("20"),
    )

    assert size.notional == Decimal("60.0")
    assert size.quantity == Decimal("3.0")


def test_position_sizer_rejects_non_entry_decision():
    decision = TradeDecision(action=TradeDecisionAction.HOLD, signal=Signal.wait())

    with pytest.raises(ValueError, match="entry decision"):
        PositionSizer(base_risk_ratio=Decimal("0.1"), leverage=Decimal("1")).size(
            decision=decision,
            exposure_limit=_limit(),
            entry_price=Decimal("10"),
        )


def test_position_sizer_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="base_risk_ratio"):
        PositionSizer(base_risk_ratio=Decimal("0"), leverage=Decimal("1"))

    with pytest.raises(ValueError, match="leverage"):
        PositionSizer(base_risk_ratio=Decimal("0.1"), leverage=Decimal("0"))

    with pytest.raises(ValueError, match="entry_price"):
        PositionSizer(base_risk_ratio=Decimal("0.1"), leverage=Decimal("1")).size(
            decision=_decision(),
            exposure_limit=_limit(),
            entry_price=Decimal("0"),
        )
