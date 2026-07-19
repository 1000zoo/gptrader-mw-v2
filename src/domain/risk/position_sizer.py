from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from src.domain.risk.exposure_limit import ExposureLimit
from src.domain.signal import TradeDecision, TradeDecisionAction

MAX_LEVERAGE = Decimal("15")


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
class PositionSizingDecision:
    equity_ratio: Decimal
    leverage: Decimal

    def __post_init__(self) -> None:
        if self.equity_ratio <= Decimal("0"):
            raise ValueError("equity_ratio must be positive")
        if self.leverage <= Decimal("0"):
            raise ValueError("leverage must be positive")
        if self.leverage > MAX_LEVERAGE:
            raise ValueError("leverage cannot exceed 15")


class PositionSizingStrategy(Protocol):
    def decide(
        self,
        decision: TradeDecision,
        exposure_limit: ExposureLimit,
    ) -> PositionSizingDecision:
        ...


@dataclass(frozen=True)
class FixedPositionSizingStrategy:
    equity_ratio: Decimal
    leverage: Decimal

    def decide(
        self,
        decision: TradeDecision,
        exposure_limit: ExposureLimit,
    ) -> PositionSizingDecision:
        return PositionSizingDecision(
            equity_ratio=self.equity_ratio,
            leverage=min(self.leverage, MAX_LEVERAGE),
        )


@dataclass(frozen=True)
class ConfidencePositionSizingStrategy:
    min_equity_ratio: Decimal = Decimal("0.01")
    max_equity_ratio: Decimal = Decimal("0.10")
    min_leverage: Decimal = Decimal("1")
    max_leverage: Decimal = Decimal("5")

    def __post_init__(self) -> None:
        if self.min_equity_ratio <= Decimal("0"):
            raise ValueError("min_equity_ratio must be positive")
        if self.max_equity_ratio < self.min_equity_ratio:
            raise ValueError("max_equity_ratio must be greater than or equal to min_equity_ratio")
        if self.min_leverage <= Decimal("0"):
            raise ValueError("min_leverage must be positive")
        if self.max_leverage < self.min_leverage:
            raise ValueError("max_leverage must be greater than or equal to min_leverage")

    def decide(
        self,
        decision: TradeDecision,
        exposure_limit: ExposureLimit,
    ) -> PositionSizingDecision:
        confidence = _clamp(decision.signal.confidence, Decimal("0"), Decimal("1"))
        equity_ratio = self.min_equity_ratio + (
            self.max_equity_ratio - self.min_equity_ratio
        ) * confidence
        leverage = self.min_leverage + (
            min(self.max_leverage, MAX_LEVERAGE) - self.min_leverage
        ) * confidence
        return PositionSizingDecision(equity_ratio=equity_ratio, leverage=leverage)


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


def _clamp(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    return max(minimum, min(value, maximum))
