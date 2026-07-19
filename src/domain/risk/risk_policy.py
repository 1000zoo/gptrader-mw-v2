from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from src.domain.risk.exposure_limit import ExposureLimit
from src.domain.signal import TradeDecision, TradeDecisionAction


class RiskDecisionReason(Enum):
    ALLOWED = "allowed"
    NOT_ENTRY_DECISION = "not_entry_decision"
    TOTAL_EXPOSURE_EXCEEDED = "total_exposure_exceeded"
    SYMBOL_EXPOSURE_EXCEEDED = "symbol_exposure_exceeded"


@dataclass(frozen=True)
class RiskCheck:
    allowed: bool
    reason: RiskDecisionReason


class RiskPolicy:
    def check_entry(
        self,
        decision: TradeDecision,
        exposure_limit: ExposureLimit,
        requested_notional: Decimal,
    ) -> RiskCheck:
        if requested_notional < Decimal("0"):
            raise ValueError("requested_notional cannot be negative")

        if decision.action not in {
            TradeDecisionAction.ENTER_LONG,
            TradeDecisionAction.ENTER_SHORT,
        }:
            return RiskCheck(
                allowed=False,
                reason=RiskDecisionReason.NOT_ENTRY_DECISION,
            )

        if requested_notional > exposure_limit.remaining_total_exposure:
            return RiskCheck(
                allowed=False,
                reason=RiskDecisionReason.TOTAL_EXPOSURE_EXCEEDED,
            )

        if requested_notional > exposure_limit.remaining_symbol_exposure:
            return RiskCheck(
                allowed=False,
                reason=RiskDecisionReason.SYMBOL_EXPOSURE_EXCEEDED,
            )

        return RiskCheck(allowed=True, reason=RiskDecisionReason.ALLOWED)
