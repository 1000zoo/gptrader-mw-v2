from decimal import Decimal

from src.domain.risk import ExposureLimit, RiskDecisionReason, RiskPolicy
from src.domain.signal import (
    Signal,
    SignalDirection,
    TradeDecision,
    TradeDecisionAction,
)


def _limit() -> ExposureLimit:
    return ExposureLimit(
        equity=Decimal("1000"),
        current_total_exposure=Decimal("200"),
        current_symbol_exposure=Decimal("50"),
        max_total_exposure_ratio=Decimal("0.8"),
        max_symbol_exposure_ratio=Decimal("0.3"),
    )


def test_risk_policy_allows_entry_within_exposure_limits():
    decision = TradeDecision(
        action=TradeDecisionAction.ENTER_LONG,
        signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.75")),
    )

    check = RiskPolicy().check_entry(
        decision=decision,
        exposure_limit=_limit(),
        requested_notional=Decimal("200"),
    )

    assert check.allowed
    assert check.reason is RiskDecisionReason.ALLOWED


def test_risk_policy_blocks_non_entry_decisions():
    decision = TradeDecision(action=TradeDecisionAction.HOLD, signal=Signal.wait())

    check = RiskPolicy().check_entry(
        decision=decision,
        exposure_limit=_limit(),
        requested_notional=Decimal("10"),
    )

    assert not check.allowed
    assert check.reason is RiskDecisionReason.NOT_ENTRY_DECISION


def test_risk_policy_blocks_total_exposure_breach_before_symbol_breach():
    decision = TradeDecision(
        action=TradeDecisionAction.ENTER_SHORT,
        signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("0.75")),
    )
    limit = ExposureLimit(
        equity=Decimal("1000"),
        current_total_exposure=Decimal("790"),
        current_symbol_exposure=Decimal("10"),
        max_total_exposure_ratio=Decimal("0.8"),
        max_symbol_exposure_ratio=Decimal("0.9"),
    )

    check = RiskPolicy().check_entry(
        decision=decision,
        exposure_limit=limit,
        requested_notional=Decimal("20"),
    )

    assert not check.allowed
    assert check.reason is RiskDecisionReason.TOTAL_EXPOSURE_EXCEEDED


def test_risk_policy_blocks_symbol_exposure_breach():
    decision = TradeDecision(
        action=TradeDecisionAction.ENTER_LONG,
        signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.75")),
    )
    limit = ExposureLimit(
        equity=Decimal("1000"),
        current_total_exposure=Decimal("100"),
        current_symbol_exposure=Decimal("290"),
        max_total_exposure_ratio=Decimal("0.8"),
        max_symbol_exposure_ratio=Decimal("0.3"),
    )

    check = RiskPolicy().check_entry(
        decision=decision,
        exposure_limit=limit,
        requested_notional=Decimal("20"),
    )

    assert not check.allowed
    assert check.reason is RiskDecisionReason.SYMBOL_EXPOSURE_EXCEEDED
