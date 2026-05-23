from dataclasses import dataclass
from decimal import Decimal

from src.domain.risk.exposure_limit import ExposureLimit
from src.domain.signal import TradeDecision, TradeDecisionAction


@dataclass(frozen=True)
class PositionSize:
    notional: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        if self.notional < Decimal("0"):
            raise ValueError("notional cannot be negative")
        if self.quantity < Decimal("0"):
            raise ValueError("quantity cannot be negative")


@dataclass(frozen=True)
class PositionSizer:
    base_risk_ratio: Decimal
    leverage: Decimal

    def __post_init__(self) -> None:
        if self.base_risk_ratio <= Decimal("0"):
            raise ValueError("base_risk_ratio must be positive")
        if self.leverage <= Decimal("0"):
            raise ValueError("leverage must be positive")

    def size(
        self,
        decision: TradeDecision,
        exposure_limit: ExposureLimit,
        entry_price: Decimal,
    ) -> PositionSize:
        if decision.action not in {
            TradeDecisionAction.ENTER_LONG,
            TradeDecisionAction.ENTER_SHORT,
        }:
            raise ValueError("position sizing requires an entry decision")
        if entry_price <= Decimal("0"):
            raise ValueError("entry_price must be positive")

        requested_notional = (
            exposure_limit.equity
            * self.base_risk_ratio
            * decision.signal.confidence
            * self.leverage
        )
        capped_notional = min(
            requested_notional,
            exposure_limit.remaining_total_exposure,
            exposure_limit.remaining_symbol_exposure,
        )

        return PositionSize(
            notional=capped_notional,
            quantity=capped_notional / entry_price,
        )
