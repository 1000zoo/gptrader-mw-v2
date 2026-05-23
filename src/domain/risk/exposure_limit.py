from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ExposureLimit:
    equity: Decimal
    current_total_exposure: Decimal
    current_symbol_exposure: Decimal
    max_total_exposure_ratio: Decimal
    max_symbol_exposure_ratio: Decimal

    def __post_init__(self) -> None:
        if self.equity <= Decimal("0"):
            raise ValueError("equity must be positive")
        if self.current_total_exposure < Decimal("0"):
            raise ValueError("current_total_exposure cannot be negative")
        if self.current_symbol_exposure < Decimal("0"):
            raise ValueError("current_symbol_exposure cannot be negative")
        if self.max_total_exposure_ratio <= Decimal("0"):
            raise ValueError("max_total_exposure_ratio must be positive")
        if self.max_symbol_exposure_ratio <= Decimal("0"):
            raise ValueError("max_symbol_exposure_ratio must be positive")

    @property
    def max_total_exposure(self) -> Decimal:
        return self.equity * self.max_total_exposure_ratio

    @property
    def max_symbol_exposure(self) -> Decimal:
        return self.equity * self.max_symbol_exposure_ratio

    @property
    def remaining_total_exposure(self) -> Decimal:
        remaining = self.max_total_exposure - self.current_total_exposure
        return max(remaining, Decimal("0"))

    @property
    def remaining_symbol_exposure(self) -> Decimal:
        remaining = self.max_symbol_exposure - self.current_symbol_exposure
        return max(remaining, Decimal("0"))

    def allows(self, new_notional: Decimal) -> bool:
        if new_notional < Decimal("0"):
            raise ValueError("new_notional cannot be negative")

        return (
            new_notional <= self.remaining_total_exposure
            and new_notional <= self.remaining_symbol_exposure
        )
